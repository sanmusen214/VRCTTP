"""
模块基类定义。

层级关系：
    BaseModule
    ├── PacketProducerModule    — 主动生产包（音频源等）
    └── PacketConsumerModule    — 被动消费队列包（翻译、识别、消费者）
                                  支持 group_by 分组合并显示（多路翻译汇聚）

生命周期钩子（子类实现，框架保证调用顺序）：
    on_start()         — 工作线程启动前
    on_before_stop()   — 发出停止信号前（适合发送"结束"信号）
    on_after_stop()    — 工作线程退出后（适合释放资源）

处理钩子（PacketConsumerModule 子类可实现）：
    pre_process(packet)              — process_packet 前，返回 None 可丢弃包
    post_process(results)            — process_packet 后，可修改结果列表

节点时间戳：
    每个模块（ref_id）在调用 send_to_downstream() 时，会自动调用
    packet.mark_node_time(ref_id)，将该时刻写入包的 data 字段。
    下游 PacketConsumerModule 若配置了 group_by="timestamp_{ref_id}"，则会把
    来自同一祖先节点的所有分叉包合并后统一渲染。

向后兼容别名（文件末尾）：
    PacketProducerModule = PacketProducerModule
    PacketConsumerModule = PacketConsumerModule
    PacketConsumerModule    = PacketConsumerModule
"""

from __future__ import annotations

import logging
import queue
import threading
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, final

from core.packet import (
    KEY_TARGET_LANG,
    KEY_TEXT_ORIGINAL,
    KEY_TEXT_TRANSLATED,
    MessagePacket,
)

logger = logging.getLogger(__name__)


class ParamType(Enum):
    """模块配置参数的数据类型枚举，供 GUI 动态渲染表单使用。"""
    String = "string"
    Int = "int"
    Float = "float"
    Bool = "bool"
    Password = "password"    # 输入框隐藏明文
    Select = "select"        # 下拉选择，需配合 selectable 字段
    DirPath = "dirpath"      # 目录路径，GUI 可提供文件夹浏览器
    FilePath = "filepath"    # 文件路径，GUI 可提供文件浏览器
    List = "list"            # 列表（JSON 数组）
    LanguageCode = "language_code"  # BCP-47 语言代码字符串


class BaseModule(ABC):
    """
    所有模块的基类。

    框架方法（@final，不得覆盖）：
        send_to_downstream, start, stop

    生命周期钩子（可覆盖，均有空的默认实现）：
        on_start, on_before_stop, on_after_stop

    Attributes:
        module_id:  完整命名空间 ID（如 "vrchat.volc_stt"），用于日志
        _ref_id:    config 中定义的本地引用 ID（如 "volc_stt"），
                    用作节点时间戳 key（"timestamp_volc_stt"）

    共享实例说明：
        当同一模块实例被多条 pipeline 共用时，start()/stop() 使用引用计数：
        只有第一个 start() 真正启动线程，只有最后一个 stop() 真正停止线程。
        包的路由完全由包自身携带（_pipeline_routes / _pipeline_modules），
        send_to_downstream() 按包内路由寻找下一跳，保证不同 pipeline 的包不会串流。
    """

    def __init__(self, module_id: str, config: dict):
        self.module_id = module_id
        self.config = config
        # 本地引用 ID：由 engine 通过 config["_ref_id"] 注入
        self._ref_id: str = config.get("_ref_id", module_id)
        _queue_size = config.get("_queue_size", 2)
        self.input_queue: queue.Queue[MessagePacket | None] = queue.Queue(maxsize=_queue_size)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        # 引用计数：支持共享模块实例被多条 pipeline 使用
        self._start_count: int = 0
        self._start_lock = threading.Lock()

    # ------------------------------------------------------------------
    # 向下游广播（@final）
    # ------------------------------------------------------------------

    @final
    def send_to_downstream(self, packet: MessagePacket) -> None:
        """
        将包按包内路由图广播至下一跳模块。
        在分发前自动为包打上本节点的时间戳（mark_node_time）。

        路由信息由 PacketProducerModule._run() 在发包时注入（_pipeline_routes /
        _pipeline_modules），全链路依赖包内路由，不使用静态连线。

        此方法标记为 final，不允许子类重写。
        """
        def _put_with_clear(q: queue.Queue, pkt: MessagePacket, ds_id: str) -> None:
            try:
                q.put_nowait(pkt)
            except queue.Full:
                logger.warning("[%s] 下游 %s 队列已满，清空旧包", self.module_id, ds_id)
                while not q.empty():
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        break
                try:
                    q.put_nowait(pkt)
                except queue.Full:
                    pass

        # 发出前打上本节点时间戳，克隆包携带该时间戳
        packet.mark_node_time(self._ref_id)

        next_refs = packet._pipeline_routes.get(self._ref_id, [])
        if not next_refs:
            return
        if len(next_refs) == 1:
            ref = next_refs[0]
            _put_with_clear(packet._pipeline_modules[ref].input_queue, packet, ref)
        else:
            for ref in next_refs:
                _put_with_clear(packet._pipeline_modules[ref].input_queue, packet.clone(), ref)

    # ------------------------------------------------------------------
    # 生命周期（@final）
    # ------------------------------------------------------------------

    @final
    def start(self) -> None:
        """
        启动模块的后台工作线程。调用顺序：on_start → 启动线程。

        引用计数：若模块实例被多条 pipeline 共用，仅第一次调用真正启动线程，
        后续调用只递增计数并返回。
        """
        with self._start_lock:
            self._start_count += 1
            if self._start_count > 1:
                logger.info(
                    "[%s] 共享实例已在运行（引用计数=%d），跳过重复启动",
                    self.module_id, self._start_count,
                )
                return
        self.on_start()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"module-{self.module_id}",
            daemon=True,
        )
        self._thread.start()
        logger.info("[%s] 已启动", self.module_id)

    @final
    def stop(self) -> None:
        """
        请求模块停止并等待线程退出。
        调用顺序：on_before_stop → 设置停止信号 → 等待线程 → on_after_stop。

        引用计数：若模块实例被多条 pipeline 共用，只有最后一个 stop() 才真正
        停止线程；其余调用只递减计数并返回。
        """
        with self._start_lock:
            if self._start_count <= 0:
                return
            self._start_count -= 1
            if self._start_count > 0:
                logger.info(
                    "[%s] 共享实例仍被引用（引用计数=%d），暂不停止",
                    self.module_id, self._start_count,
                )
                return
        self.on_before_stop()
        self._stop_event.set()
        # 投入哨兵值让阻塞的 get() 立刻返回
        try:
            self.input_queue.put_nowait(None)
        except queue.Full:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("[%s] 已停止", self.module_id)
        self.on_after_stop()

    # ------------------------------------------------------------------
    # 生命周期钩子（可覆盖）
    # ------------------------------------------------------------------

    def on_start(self) -> None:
        """Hook: 在工作线程启动前被调用。子类可覆盖执行初始化。"""

    def on_before_stop(self) -> None:
        """Hook: 在发出停止信号前被调用。子类可覆盖（如发送结束帧）。"""

    def on_after_stop(self) -> None:
        """Hook: 在工作线程退出后被调用。子类可覆盖执行资源释放。"""

    # ------------------------------------------------------------------
    # 模块元信息（@classmethod @abstractmethod，子类须实现）
    # ------------------------------------------------------------------

    @classmethod
    @abstractmethod
    def require_attributes_in_packages(cls) -> list[dict]:
        """
        声明本模块从上游包中读取哪些字段。

        返回字段描述列表，每项格式：
            {
                "name": str,          # 字段名（对应 MessagePacket.data 的 key）
                "must_have": bool,    # True = 必须存在，False = 可选
                "description": str,   # 字段用途说明
            }
        """

    @classmethod
    @abstractmethod
    def add_attributes_in_packages(cls) -> list[dict]:
        """
        声明本模块向下游包中写入哪些字段。

        返回字段描述列表，格式同 require_attributes_in_packages。
        """

    @classmethod
    @abstractmethod
    def get_config_attributes(cls) -> list[dict]:
        """
        声明本模块支持的配置参数，供 GUI 动态渲染表单。

        返回参数描述列表，每项格式：
            {
                "name": str,              # 参数名（对应 config["params"] 的 key）
                "type": ParamType,        # 参数类型
                "default": Any,           # 默认值（None 表示无默认）
                "required": bool,         # 是否必填
                "description": str,       # 参数说明
                "selectable": list | None, # Select 类型的选项列表
                "min": Any,               # Int/Float 的最小值（可选）
                "max": Any,               # Int/Float 的最大值（可选）
            }
        """

    # ------------------------------------------------------------------
    # 内部运行循环（@abstractmethod，由子类 final 化）
    # ------------------------------------------------------------------

    @abstractmethod
    def _run(self) -> None:
        """后台工作线程主循环。子类须实现，框架负责调用。"""




# ---------------------------------------------------------------------------
# PacketProducerModule — 主动生产包
# ---------------------------------------------------------------------------

class PacketProducerModule(BaseModule):
    """
    包生产模块。

    主动产生 MessagePacket，不依赖 input_queue。
    子类须实现：
        produce_packets() — 生成器，持续 yield MessagePacket

    子类不得覆盖 _run()（已 @final）。

    set_pipeline_context(routes, modules) 由 Pipeline.build() 调用，
    将路由图注入生产者；_run() 在每个包发出前将其写入 packet._pipeline_routes /
    packet._pipeline_modules，确保包在整条 pipeline 内按正确路由流动。
    """

    def __init__(self, module_id: str, config: dict) -> None:
        super().__init__(module_id, config)
        # 由 Pipeline.build() 注入，供 _run() 写入每个产出的包
        self._pipeline_routes: dict[str, list[str]] = {}
        self._pipeline_modules: dict[str, Any] = {}

    def set_pipeline_context(
        self,
        routes: dict[str, list[str]],
        modules: dict[str, Any],
    ) -> None:
        """
        由 Pipeline.build() 调用，注入本 pipeline 的路由图与模块字典。
        _run() 会将这两个引用写入每个产出的包，驱动包的全链路路由。
        """
        self._pipeline_routes = routes
        self._pipeline_modules = modules

    @final
    def _run(self) -> None:
        """直接迭代 produce_packets()，注入路由上下文后广播给下游。

        路由注入规则：
        - 包已有路由信息（转发自上游的包）：保持原有路由不覆盖。
        - 包无路由信息（本模块新建的包）：写入本 pipeline 路由。
        """
        try:
            for packet in self.produce_packets():
                if self._stop_event.is_set():
                    break
                # 仅对新建包注入路由；转发自上游的包已携带正确路由，不覆盖
                if not packet._pipeline_routes:
                    packet._pipeline_routes = self._pipeline_routes
                    packet._pipeline_modules = self._pipeline_modules
                self.send_to_downstream(packet)
        except Exception:
            logger.exception("[%s] 产包出错", self.module_id)

    @abstractmethod
    def produce_packets(self):
        """
        生成器：持续捕获/产生 MessagePacket。
        当 _stop_event 被置位时应尽快退出。
        """

    def process_packet(self, packet: MessagePacket) -> list[MessagePacket]:
        """生产者模块不消费输入包，此方法通常不被调用。"""
        return []


# ---------------------------------------------------------------------------
# PacketConsumerModule — 被动消费队列包（替代 PacketConsumerModule + ConsumerModule）
# ---------------------------------------------------------------------------

class PacketConsumerModule(BaseModule):
    """
    包消费模块。

    从 input_queue 接收包，处理后可选择发往下游。
    支持 group_by 分组合并显示（多路翻译结果汇聚）。

    子类须实现：
        process_packet(packet) — 处理单个包，返回结果列表

    子类可覆盖以下钩子（均有默认实现）：
        pre_process(packet)              — 前置处理，返回 None 可丢弃包
        post_process(results)            — 后置处理，可修改结果列表

    子类不得覆盖 _run()、_dispatch()（均已 @final）。

    Config 参数：
        group_by (str): 分组 key，如 "timestamp_volc_stt"，默认 "" 表示不分组
    """

    def __init__(self, module_id: str, config: dict) -> None:
        super().__init__(module_id, config)
        
    

    # ------------------------------------------------------------------
    # 内部运行循环（@final）
    # ------------------------------------------------------------------

    @final
    def _run(self) -> None:
        """从 input_queue 取包，分发"""
        while not self._stop_event.is_set():
            try:
                packet = self.input_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if packet is None:
                break
            try:
                self._dispatch(packet)
            except Exception:
                logger.exception("[%s] 处理包时出错", self.module_id)

    @final
    def _dispatch(self, packet: MessagePacket) -> None:
        """
        分发单个包，调用链：
        pre_process → process_packet → post_process → send_to_downstream（每个结果）。
        """
        packet = self.pre_process(packet)
        if packet is None:
            return
        results = self.process_packet(packet)
        results = self.post_process(results)
        for out_packet in results:
            self.send_to_downstream(out_packet)

    # ------------------------------------------------------------------
    # 处理钩子（可覆盖）
    # ------------------------------------------------------------------

    def pre_process(self, packet: MessagePacket) -> MessagePacket | None:
        """
        前置处理钩子。在 process_packet 前调用。
        返回 None 则丢弃该包（不调用 process_packet）。默认透传。
        """
        return packet

    def post_process(self, results: list[MessagePacket]) -> list[MessagePacket]:
        """
        后置处理钩子。在 process_packet 后调用。
        可对结果列表做过滤或修改。默认透传。
        """
        return results

    # ------------------------------------------------------------------
    # 子类须实现
    # ------------------------------------------------------------------

    @abstractmethod
    def process_packet(self, packet: MessagePacket) -> list[MessagePacket]:
        """
        处理输入包，返回产生的新包列表（可为空列表）。
        若无需向下游发包（如纯消费模块），返回 [] 即可。
        """


