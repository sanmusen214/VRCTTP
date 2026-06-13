"""
Pipeline — 将一组模块连接成有向无环图（DAG）数据管道。

支持分叉路由（fan-out），例如：
    PacketProducerModule → STT → MT_ZH ─┬─ TerminalConsumer
                                MT_JA ─┘

一个 Pipeline 对应 config.json 中的一条 pipelines[] 配置项。
路由通过 graph.routes 以邻接表的形式描述：
    {
        "entry": "volc_stt",
        "routes": {
            "volc_stt": ["mt_zh", "mt_ja"],
            "mt_zh":    ["terminal_out", "osc_out"],
            "mt_ja":    ["terminal_out", "osc_out"]
        }
    }
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from core.module import PacketProducerModule, BaseModule, PacketConsumerModule, PacketProducerModule, PacketConsumerModule

logger = logging.getLogger(__name__)


@dataclass
class Pipeline:
    """
    单条翻译管道（DAG 版本）。

    Attributes:
        pipeline_id:  管道唯一标识（来自配置文件）
        name:         管道可读名称
        audio_source: 音频源模块
        all_modules:  {ref_id: 模块实例} — 除音频源外的所有模块
        routes:       {from_ref_id: [to_ref_id, ...]} 邻接表路由
        entry:        紧接音频源的第一个模块 ref_id
    """

    pipeline_id: str
    name: str
    all_modules: dict[str, BaseModule]
    routes: dict[str, list[str]] = field(default_factory=dict)
    entry: str = ""

    def __post_init__(self) -> None:
        if not self.entry:
            raise ValueError(f"Pipeline [{self.pipeline_id}] 的 entry 不能为空")
        if self.entry not in self.all_modules:
            raise ValueError(
                f"Pipeline [{self.pipeline_id}] entry='{self.entry}' 不在 all_modules 中"
            )
        if not isinstance(self.all_modules[self.entry], PacketProducerModule):
            raise TypeError(
                f"Pipeline [{self.pipeline_id}] entry='{self.entry}' 必须是 PacketProducerModule，"
                f"实际类型: {type(self.all_modules[self.entry]).__name__}"
            )
        self._wired = False

    @property
    def audio_source(self) -> PacketProducerModule:
        """音频源模块（图的根节点，即 entry）。"""
        return self.all_modules[self.entry]  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # 向后兼容属性
    # ------------------------------------------------------------------

    @property
    def translation_chain(self) -> list[PacketConsumerModule]:
        """返回所有 PacketConsumerModule 实例（顺序不定，仅用于状态展示）。"""
        return [m for m in self.all_modules.values() if isinstance(m, PacketConsumerModule)]

    @property
    def consumers(self) -> list[PacketConsumerModule]:
        """返回所有 PacketConsumerModule 实例。"""
        return [m for m in self.all_modules.values() if isinstance(m, PacketConsumerModule)]

    @property
    def translation(self) -> PacketConsumerModule:
        """返回拓扑序中第一个 PacketConsumerModule（向后兼容）。"""
        for m in self._topological_order():
            if isinstance(m, PacketConsumerModule):
                return m
        raise AttributeError(f"Pipeline [{self.pipeline_id}] 中找不到 PacketConsumerModule")

    # ------------------------------------------------------------------
    # 连线
    # ------------------------------------------------------------------

    def build(self) -> None:
        """
        校验路由图并将路由上下文注入入口（生产者）模块。

        不再通过 add_downstream() 硬连线模块：路由信息由入口模块注入到它产出的每个包中，
        消费模块通过包内的 _pipeline_routes / _pipeline_modules 进行动态寻路，
        从而支持多条 pipeline 共用同一模块实例而包不串流。
        """
        if self._wired:
            return

        # 校验所有路由引用的 ref_id 均已在 all_modules 中定义
        for from_ref, to_refs in self.routes.items():
            if from_ref not in self.all_modules:
                raise ValueError(
                    f"Pipeline [{self.pipeline_id}] routes 中 '{from_ref}' 未在 all_modules 中定义"
                )
            for to_ref in to_refs:
                if to_ref not in self.all_modules:
                    raise ValueError(
                        f"Pipeline [{self.pipeline_id}] routes 中 '{to_ref}' 未在 all_modules 中定义"
                    )

        # 将本 pipeline 的路由图注入所有 PacketProducerModule 节点
        # （入口龙头及内嵌在 DAG 中的中间生产者，如 TextInput）
        for ref_id, module in self.all_modules.items():
            if hasattr(module, "set_pipeline_context"):
                module.set_pipeline_context(self.routes, self.all_modules)

        self._wired = True
        logger.debug(
            "Pipeline [%s] 已构建路由上下文 entry=%s routes=%s",
            self.pipeline_id,
            self.entry,
            self.routes,
        )

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def _topological_order(self) -> list[BaseModule]:
        """
        对 all_modules 做拓扑排序，返回从 entry 到 consumers 的顺序列表。
        用于按正确顺序启动 / 停止模块（消费者最后启动，最先停止）。
        """
        visited: set[str] = set()
        order: list[str] = []

        def dfs(ref: str) -> None:
            if ref in visited:
                return
            visited.add(ref)
            for nxt in self.routes.get(ref, []):
                dfs(nxt)
            order.append(ref)

        dfs(self.entry)
        # order 现在是反拓扑序（entry 最后），翻转得到正序
        order.reverse()
        # 补全未被 routes 覆盖的节点（孤立消费者等）
        for ref in self.all_modules:
            if ref not in visited:
                order.append(ref)
        return [self.all_modules[r] for r in order]

    def start(self) -> None:
        """按拓扑逆序启动模块（消费者先启，音频源最后）。"""
        self.build()
        for module in reversed(self._topological_order()):
            module.start()
        logger.info("Pipeline [%s] '%s' 已启动", self.pipeline_id, self.name)

    def stop(self) -> None:
        """按拓扑序停止模块（音频源先停，消费者最后停）。"""
        for module in self._topological_order():
            module.stop()
        logger.info("Pipeline [%s] '%s' 已停止", self.pipeline_id, self.name)

    def is_alive(self) -> bool:
        """返回音频源线程是否仍在运行。"""
        t = self.audio_source._thread
        return t is not None and t.is_alive()

    @property
    def status(self) -> str:
        return "running" if self.is_alive() else "stopped"
