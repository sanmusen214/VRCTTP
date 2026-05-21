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
from typing import final

from core.packet import (
    KEY_TARGET_LANG,
    KEY_TEXT_ORIGINAL,
    KEY_TEXT_TRANSLATED,
    MessagePacket,
)

logger = logging.getLogger(__name__)


class BaseModule(ABC):
    """
    所有模块的基类。

    框架方法（@final，不得覆盖）：
        add_downstream, send_to_downstream, start, stop

    生命周期钩子（可覆盖，均有空的默认实现）：
        on_start, on_before_stop, on_after_stop

    Attributes:
        module_id:  完整命名空间 ID（如 "vrchat.volc_stt"），用于日志
        _ref_id:    config 中定义的本地引用 ID（如 "volc_stt"），
                    用作节点时间戳 key（"timestamp_volc_stt"）
    """

    def __init__(self, module_id: str, config: dict):
        self.module_id = module_id
        self.config = config
        # 本地引用 ID：由 engine 通过 config["_ref_id"] 注入
        self._ref_id: str = config.get("_ref_id", module_id)
        self._downstream: list[BaseModule] = []
        self.input_queue: queue.Queue[MessagePacket | None] = queue.Queue(maxsize=200)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # 下游管理（@final）
    # ------------------------------------------------------------------

    @final
    def add_downstream(self, module: BaseModule) -> None:
        """连接一个下游模块。一个模块可以有多个下游。"""
        self._downstream.append(module)

    # ------------------------------------------------------------------
    # 向下游广播（@final）
    # ------------------------------------------------------------------

    @final
    def send_to_downstream(self, packet: MessagePacket) -> None:
        """
        将包广播至所有下游模块。
        在分发前自动为包打上本节点的时间戳（mark_node_time）。
        若只有一个下游，直接传递原包；若有多个，每个下游获得一份克隆。

        此方法标记为 final，不允许子类重写。
        """
        if not self._downstream:
            return
        # 发出前打上本节点时间戳，克隆包会携带该时间戳
        packet.mark_node_time(self._ref_id)
        if len(self._downstream) == 1:
            try:
                self._downstream[0].input_queue.put_nowait(packet)
            except queue.Full:
                logger.warning(
                    "[%s] 下游 %s 队列已满，丢弃包",
                    self.module_id, self._downstream[0].module_id,
                )
        else:
            for ds in self._downstream:
                try:
                    ds.input_queue.put_nowait(packet.clone())
                except queue.Full:
                    logger.warning(
                        "[%s] 下游 %s 队列已满，丢弃包",
                        self.module_id, ds.module_id,
                    )

    # ------------------------------------------------------------------
    # 生命周期（@final）
    # ------------------------------------------------------------------

    @final
    def start(self) -> None:
        """启动模块的后台工作线程。调用顺序：on_start → 启动线程。"""
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
        """
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
    # 内部运行循环（@abstractmethod，由子类 final 化）
    # ------------------------------------------------------------------

    @abstractmethod
    def _run(self) -> None:
        """后台工作线程主循环。子类须实现，框架负责调用。"""




# ---------------------------------------------------------------------------
# PacketProducerModule — 主动生产包（替代 PacketProducerModule）
# ---------------------------------------------------------------------------

class PacketProducerModule(BaseModule):
    """
    包生产模块。

    主动产生 MessagePacket，不依赖 input_queue。
    子类须实现：
        produce_packets() — 生成器，持续 yield MessagePacket

    子类不得覆盖 _run()（已 @final）。
    """

    @final
    def _run(self) -> None:
        """直接迭代 produce_packets()，将每个包广播给下游。"""
        try:
            for packet in self.produce_packets():
                if self._stop_event.is_set():
                    break
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


