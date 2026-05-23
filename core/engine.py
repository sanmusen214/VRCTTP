"""
PipelineEngine — 从配置文件加载并管理所有 Pipeline。

职责：
  - 解析 config.json
  - 将 type 字符串映射到具体模块类（注册表模式）
  - 实例化模块并构建 Pipeline 对象
  - 统一启动 / 停止 / 状态查询
  - 支持 ${ENV_VAR} 配置占位符替换
  - 支持热重载（reload_config）
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from core.module import BaseModule, PacketConsumerModule, PacketProducerModule
from core.pipeline import Pipeline

# 延迟导入具体模块类，避免循环依赖
from modules.audio.loopback import LoopbackSource
from modules.audio.microphone import MicrophoneSource
from modules.consumer.osc_vrchat import VRChatOSCConsumer
from modules.consumer.terminal import TerminalConsumer
from modules.filter.packet_filter import PacketFilter
from modules.translation.baidu_machine_translation import BaiduMachineTranslation
from modules.translation.LocalSTTModel import LocalParaformerSTT
from modules.translation.volc_machine_translation import VolcMachineTranslation
from modules.translation.volc_streaming_stt import VolcStreamingSTT

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 模块注册表：type 字符串 → 模块类
# 添加新类型只需在此注册，无需修改其他核心代码
# ---------------------------------------------------------------------------

PRODUCER_REGISTRY: dict[str, type[PacketProducerModule]] = {
    "microphone": MicrophoneSource,
    "loopback": LoopbackSource,
}

MODULE_REGISTRY: dict[str, type[PacketConsumerModule]] = {
    "volc_streaming_stt": VolcStreamingSTT,
    "local_stt": LocalParaformerSTT,
    "volc_machine_translation": VolcMachineTranslation,
    "baidu_machine_translation": BaiduMachineTranslation,
    "terminal": TerminalConsumer,
    "osc_vrchat": VRChatOSCConsumer,
    "filter": PacketFilter,
}

_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _resolve_env_vars(obj: Any) -> Any:
    """
    递归替换配置对象中的 ${ENV_VAR} 占位符。
    支持 str、dict、list 类型的递归处理。
    """
    if isinstance(obj, str):
        def replace(m: re.Match) -> str:
            key = m.group(1)
            value = os.environ.get(key)
            if value is None:
                logger.warning("环境变量 '%s' 未设置，保留原占位符", key)
                return m.group(0)
            return value
        return _ENV_VAR_PATTERN.sub(replace, obj)
    if isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_vars(item) for item in obj]
    return obj


class PipelineEngine:
    """
    管理所有 Pipeline 的引擎。

    Usage::

        engine = PipelineEngine("config.json")
        engine.start_all()
        ...
        engine.stop_all()
    """

    def __init__(self, config_path: str = "config.json") -> None:
        self.config_path = config_path
        self._pipelines: dict[str, Pipeline] = {}
        self._raw_config: dict = {}
        # GUI 可订阅此回调获取实时消息（pipeline_id, text_original, text_translated）
        self.on_translation: list[Any] = []

    # ------------------------------------------------------------------
    # 配置加载
    # ------------------------------------------------------------------

    def load_config(self) -> None:
        """从磁盘加载并解析配置文件。"""
        with open(self.config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        self._raw_config = _resolve_env_vars(raw)
        logger.info("已加载配置文件: %s", self.config_path)

    def save_config(self, config_dict: dict) -> None:
        """将配置字典写回磁盘（保留注释不可能，但保留缩进格式）。"""
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config_dict, f, ensure_ascii=False, indent=2)
        logger.info("配置已保存至: %s", self.config_path)

    def get_raw_config(self) -> dict:
        """返回未做环境变量替换的原始配置（供 GUI 编辑器展示）。"""
        with open(self.config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_module_classes(self) -> dict[str, type[BaseModule]]:
        """返回所有已注册模块类型的注册表（type 字符串 → 类）。"""
        return {**PRODUCER_REGISTRY, **MODULE_REGISTRY}

    # ------------------------------------------------------------------
    # 构建 Pipeline
    # ------------------------------------------------------------------

    def _build_pipeline(self, pipeline_cfg: dict) -> Pipeline:
        """根据单条 pipeline 配置构建 Pipeline 对象。自动识别新/旧格式。"""
        pid = pipeline_cfg["id"]
        name = pipeline_cfg.get("name", pid)

        if "graph" in pipeline_cfg:
            # ── 新格式：所有模块均在全局 modules 注册，DAG 路由描述连接
            return self._build_dag_pipeline(pid, name, pipeline_cfg)
        else:
            # ── 旧格式：内联 audio_source + translations[] + consumers[]（向后兼容）
            return self._build_legacy_pipeline(pid, name, pipeline_cfg)

    def _build_dag_pipeline(
        self,
        pid: str,
        name: str,
        pipeline_cfg: dict,
    ) -> Pipeline:
        """
        新格式：所有模块（音频源、翻译、消费者）均在全局 modules 字典中定义，
        pipeline 仅通过 graph.entry + graph.routes 描述连接拓扑。
        """
        graph_cfg = pipeline_cfg["graph"]
        entry: str = graph_cfg["entry"]
        routes: dict[str, list[str]] = graph_cfg.get("routes", {})

        # 汇总所有需要实例化的 ref_id
        all_refs: set[str] = {entry}
        for from_ref, to_refs in routes.items():
            all_refs.add(from_ref)
            all_refs.update(to_refs)

        global_modules_cfg: dict = self._raw_config.get("modules", {})

        all_modules: dict[str, BaseModule] = {}
        for ref_id in all_refs:
            if ref_id not in global_modules_cfg:
                raise ValueError(
                    f"Pipeline [{pid}] 中 ref_id='{ref_id}' 未在全局 modules 字典中定义"
                )
            mod_def = global_modules_cfg[ref_id]
            mod_type = mod_def["type"]
            params = dict(mod_def.get("params", {}))
            params["_ref_id"] = ref_id
            params["pipeline_id"] = pid

            # print(f"构建模块 pid='{pid}' ref_id='{ref_id}' type='{mod_type}'")

            if mod_type in PRODUCER_REGISTRY:
                module: BaseModule = PRODUCER_REGISTRY[mod_type](
                    module_id=f"{pid}.{ref_id}", config=params
                )
            elif mod_type in MODULE_REGISTRY:
                params["pipeline_name"] = name
                module = MODULE_REGISTRY[mod_type](
                    module_id=f"{pid}.{ref_id}", config=params
                )
            else:
                raise ValueError(
                    f"未知模块类型: {mod_type!r}（ref_id='{ref_id}'）。"
                    f" 可用生产者: {list(PRODUCER_REGISTRY)}"
                    f" 可用消费/翻译: {list(MODULE_REGISTRY)}"
                )
            all_modules[ref_id] = module

        return Pipeline(
            pipeline_id=pid,
            name=name,
            all_modules=all_modules,
            routes=routes,
            entry=entry,
        )

    def _build_legacy_pipeline(
        self,
        pid: str,
        name: str,
        pipeline_cfg: dict,
    ) -> Pipeline:
        """
        旧格式：内联 audio_source + translations[] + consumers[] 列表，
        转换为等价的 DAG Pipeline（音频源作为 entry 放入 all_modules）。
        """
        # 音频源
        src_cfg = pipeline_cfg["audio_source"]
        src_type = src_cfg["type"]
        src_params = dict(src_cfg.get("params", {}))
        src_params["_ref_id"] = "audio"
        src_params["pipeline_id"] = pid
        if src_type not in PRODUCER_REGISTRY:
            raise ValueError(f"未知音频源类型: {src_type!r}，可用: {list(PRODUCER_REGISTRY)}")
        audio_mod: BaseModule = PRODUCER_REGISTRY[src_type](
            module_id=f"{pid}.audio", config=src_params
        )
        all_modules: dict[str, BaseModule] = {"audio": audio_mod}

        # 翻译模块链
        tr_configs_raw: list[dict] = []
        if "translations" in pipeline_cfg:
            tr_configs_raw = pipeline_cfg["translations"]
        elif "translation" in pipeline_cfg:
            tr_configs_raw = [pipeline_cfg["translation"]]
        else:
            raise ValueError(
                f"Pipeline [{pid}] 缺少 'translation'/'translations'/'graph' 配置"
            )
        if not tr_configs_raw:
            raise ValueError(f"Pipeline [{pid}] translation_chain 不能为空")

        tr_ref_ids: list[str] = []
        for idx, tr_cfg in enumerate(tr_configs_raw):
            ref_id = f"step_{idx}"
            tr_type = tr_cfg["type"]
            params = dict(tr_cfg.get("params", {}))
            params["_ref_id"] = ref_id
            params["pipeline_id"] = pid
            if tr_type not in MODULE_REGISTRY:
                raise ValueError(
                    f"未知翻译类型: {tr_type!r}，可用: {list(MODULE_REGISTRY)}"
                )
            module: BaseModule = MODULE_REGISTRY[tr_type](
                module_id=f"{pid}.translation.{idx}", config=params
            )
            all_modules[ref_id] = module
            tr_ref_ids.append(ref_id)

        consumer_ref_ids: list[str] = []
        for idx, con_cfg in enumerate(pipeline_cfg.get("consumers", [])):
            ref_id = f"consumer_{idx}"
            con_type = con_cfg["type"]
            params = dict(con_cfg.get("params", {}))
            params["_ref_id"] = ref_id
            params["pipeline_id"] = pid
            params["pipeline_name"] = name
            if con_type not in MODULE_REGISTRY:
                raise ValueError(
                    f"未知消费类型: {con_type!r}，可用: {list(MODULE_REGISTRY)}"
                )
            module = MODULE_REGISTRY[con_type](
                module_id=f"{pid}.consumer.{idx}", config=params
            )
            all_modules[ref_id] = module
            consumer_ref_ids.append(ref_id)

        # 构建线性路由（含音频源 → 翻译链第一环）
        routes: dict[str, list[str]] = {"audio": [tr_ref_ids[0]]}
        for i in range(len(tr_ref_ids) - 1):
            routes[tr_ref_ids[i]] = [tr_ref_ids[i + 1]]
        if consumer_ref_ids:
            routes[tr_ref_ids[-1]] = consumer_ref_ids

        return Pipeline(
            pipeline_id=pid,
            name=name,
            all_modules=all_modules,
            routes=routes,
            entry="audio",
        )

    def build_all(self) -> None:
        """构建所有已启用的 Pipeline（不启动）。"""
        if not self._raw_config:
            self.load_config()
        self._pipelines.clear()
        for pcfg in self._raw_config.get("pipelines", []):
            if not pcfg.get("enabled", True):
                logger.info("Pipeline [%s] 已禁用，跳过", pcfg.get("id"))
                continue
            try:
                pipeline = self._build_pipeline(pcfg)
                self._pipelines[pipeline.pipeline_id] = pipeline
                logger.info("Pipeline [%s] 构建完成", pipeline.pipeline_id)
            except Exception:
                logger.exception("构建 Pipeline [%s] 失败", pcfg.get("id"))

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start_all(self) -> None:
        """启动所有 Pipeline。"""
        if not self._pipelines:
            self.build_all()
        for pipeline in self._pipelines.values():
            try:
                pipeline.start()
            except Exception:
                logger.exception("启动 Pipeline [%s] 失败", pipeline.pipeline_id)

    def stop_all(self) -> None:
        """停止所有 Pipeline。"""
        for pipeline in self._pipelines.values():
            try:
                pipeline.stop()
            except Exception:
                logger.exception("停止 Pipeline [%s] 失败", pipeline.pipeline_id)

    def start_pipeline(self, pipeline_id: str) -> None:
        """启动单条 Pipeline（需先 build_all）。"""
        pipeline = self._pipelines.get(pipeline_id)
        if pipeline is None:
            raise KeyError(f"Pipeline '{pipeline_id}' 不存在")
        pipeline.start()

    def stop_pipeline(self, pipeline_id: str) -> None:
        """停止单条 Pipeline。"""
        pipeline = self._pipelines.get(pipeline_id)
        if pipeline is None:
            raise KeyError(f"Pipeline '{pipeline_id}' 不存在")
        pipeline.stop()

    def reload_config(self) -> None:
        """
        热重载：停止所有 Pipeline，重新加载配置并启动。
        GUI 保存配置后应调用此方法。
        """
        logger.info("开始热重载配置...")
        self.stop_all()
        self.load_config()
        self.build_all()
        self.start_all()
        logger.info("热重载完成")

    # ------------------------------------------------------------------
    # 状态查询（供 GUI 使用）
    # ------------------------------------------------------------------

    def get_status(self) -> list[dict]:
        """
        返回所有 Pipeline 的状态摘要列表。

        每个元素::

            {
                "id": "vrchat_en_to_zh",
                "name": "VRChat英语→中文",
                "status": "running" | "stopped",
                "audio_source_type": "loopback",
                "translation_type": "whisper_batch",
                "consumer_types": ["terminal", "osc_vrchat"],
            }
        """
        result = []
        for pid, pipeline in self._pipelines.items():
            result.append({
                "id": pid,
                "name": pipeline.name,
                "status": pipeline.status,
                "audio_source_type": type(pipeline.audio_source).__name__,
                "translation_types": [type(m).__name__ for m in pipeline.translation_chain],
                "translation_type": type(pipeline.translation).__name__,  # 向后兼容（首模块）
                "consumer_types": [type(c).__name__ for c in pipeline.consumers],
            })
        return result

    def get_gui_config(self) -> dict:
        """返回 GUI 相关配置（host, port 等）。"""
        return self._raw_config.get("gui", {})

    def list_pipelines(self) -> list[str]:
        return list(self._pipelines.keys())
