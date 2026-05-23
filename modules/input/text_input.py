"""
TextInput — 文字输入模块（支持透传与直接输入）。

具有两项主要功能：
1. 承接并直接透传上游输入端的内容（兼容被放置在 pipeline 中层的情况）。
2. 直接由用户从 GUI 输入文字，产生与 STT 模块输出字段相同的 MessagePacket，
随后沿 pipeline 向下游传递。

字段说明（输出包与 STT 模块一致）：
    text_original   — 用户输入的文字（原文）
    source_lang     — 来源语言代码（config 配置，默认 "auto"）
    is_partial      — 始终 False（文字输入无流式中间结果）
    is_final_segment— 始终 True
    source_type     — "text_input"
    source_name     — 本实例的 ref_id

与 GUI 协同方式：
    GUI 通过 TextInput._instances[module_id] 取得运行中的实例，
    调用 submit_text(text) 将文字投入内部队列，produce_packets() 
    交替轮询内部队列与上游输入队列，最终将包传递至下游。
"""

from __future__ import annotations

import queue
import time
import logging

from core.module import PacketProducerModule, ParamType
from core.packet import (
    KEY_IS_FINAL_SEGMENT,
    KEY_IS_PARTIAL,
    KEY_SOURCE_LANG,
    KEY_SOURCE_NAME,
    KEY_SOURCE_TYPE,
    KEY_TEXT_ORIGINAL,
    MessagePacket,
)

logger = logging.getLogger(__name__)


class TextInput(PacketProducerModule):
    """
    文字输入模块。用户在 GUI 输入框中输入文字，模块将其封装为包发往下游。
    """

    # 全局注册表：module_id → 运行中的 TextInput 实例
    # GUI 通过此表访问活跃实例，调用 submit_text()
    _instances: dict[str, "TextInput"] = {}

    def on_start(self) -> None:
        self._text_queue: queue.Queue[str] = queue.Queue()
        TextInput._instances[self.module_id] = self
        logger.info("[%s] TextInput 已注册到全局实例表", self.module_id)

    def on_after_stop(self) -> None:
        TextInput._instances.pop(self.module_id, None)
        logger.info("[%s] TextInput 已从全局实例表移除", self.module_id)

    def submit_text(self, text: str) -> None:
        """
        由 GUI 线程调用，将用户输入的文字投入内部队列。
        线程安全（queue.Queue 内部加锁）。
        """
        if text:
            self._text_queue.put(text)

    def produce_packets(self):
        """
        处理两类输入源：
        1. 内部文字队列（由 GUI 投入）：组装为 MessagePacket 原文包并发出。
        2. 上游传入的包（self.input_queue）：直接透传给下游。
        使用简短超时交替轮询两者。
        """
        pipeline_id: str = self.config.get("pipeline_id", "")
        source_lang: str = self.config.get("source_lang", "auto")

        while not self._stop_event.is_set():
            # 1. 优先处理所有来自 GUI 的文字输入
            while True:
                try:
                    text = self._text_queue.get_nowait()
                    packet = MessagePacket(pipeline_id=pipeline_id)
                    packet.data[KEY_TEXT_ORIGINAL] = text
                    packet.data[KEY_SOURCE_LANG] = source_lang
                    packet.data[KEY_IS_PARTIAL] = False
                    packet.data[KEY_IS_FINAL_SEGMENT] = True
                    packet.data[KEY_SOURCE_TYPE] = "text_input"
                    packet.data[KEY_SOURCE_NAME] = self._ref_id

                    logger.debug("[%s] 发出文字包: %r", self.module_id, text)
                    yield packet
                except queue.Empty:
                    break

            # 2. 处理上游传来的包（透传）
            try:
                # 阻塞 0.1 秒，降低 CPU 占用，同时确保能及时检查 _text_queue 和 stop_event
                in_packet = self.input_queue.get(timeout=0.1)
                if in_packet is not None:
                    # 直接透传上游来的包
                    yield in_packet
            except queue.Empty:
                pass

    @classmethod
    def require_attributes_in_packages(cls) -> list[dict]:
        return []

    @classmethod
    def add_attributes_in_packages(cls) -> list[dict]:
        return [
            {"name": "text_original",    "must_have": True,  "description": "用户输入的原文"},
            {"name": "source_lang",      "must_have": True,  "description": "来源语言代码（config 配置）"},
            {"name": "is_partial",       "must_have": True,  "description": "始终 False"},
            {"name": "is_final_segment", "must_have": True,  "description": "始终 True"},
            {"name": "source_type",      "must_have": True,  "description": "固定为 \"text_input\""},
            {"name": "source_name",      "must_have": True,  "description": "本实例的 ref_id"},
        ]

    @classmethod
    def get_config_attributes(cls) -> list[dict]:
        return [
            {
                "name": "source_lang",
                "type": ParamType.LanguageCode,
                "default": "auto",
                "required": False,
                "description": "输出包的来源语言代码，如 \"zh\"、\"en\"、\"auto\"",
                "selectable": None,
            },
        ]
