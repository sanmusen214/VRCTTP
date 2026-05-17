"""
PacketConsumerModule 基类。

定义翻译模块共用的接口和配置结构。
"""

from __future__ import annotations

import logging

from core.module import PacketConsumerModule

logger = logging.getLogger(__name__)


class BasePacketConsumerModule(PacketConsumerModule):
    """
    翻译模块公共基类。

    Config 参数（所有翻译模块共用）：
        api_key (str): OpenAI API Key，支持 ${ENV_VAR} 替换（由 engine 处理）
        base_url (str): API Base URL，默认 https://api.openai.com/v1
        source_language (str): 原文语言代码，如 "en"（留空则自动检测）
        target_language (str): 目标语言代码，如 "zh"
        pipeline_id (str): 所属管道 ID（由 engine 注入）
    """

    def __init__(self, module_id: str, config: dict) -> None:
        super().__init__(module_id, config)
        self._api_key: str = config.get("api_key", "")
        self._base_url: str = config.get("base_url", "https://api.openai.com/v1")
        self._source_language: str = config.get("source_language", "")
        self._target_language: str = config.get("target_language", "zh")
        self._pipeline_id: str = config.get("pipeline_id", "unknown")


