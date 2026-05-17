"""
TerminalConsumer — 将翻译结果打印到终端。

Config 参数：
    color (bool): 是否使用 colorama 彩色输出，默认 True
    format (str): 输出格式字符串，可用占位符:
                  {pipeline_name}, {text_original}, {text_translated},
                  {source_lang}, {target_lang}
                  默认: "[{pipeline_name}] {text_original} → {text_translated}"
    pipeline_name (str): 由 engine 注入的管道名称
    pipeline_id (str): 由 engine 注入的管道 ID

同时，若 engine 注册了 on_text_callback，也会调用它（供 GUI 消费）。
"""

from __future__ import annotations

import logging
import sys
from typing import Callable

from core.packet import (
    KEY_IS_PARTIAL,
    KEY_SOURCE_LANG,
    KEY_TARGET_LANG,
    KEY_TEXT_ORIGINAL,
    KEY_TEXT_TRANSLATED,
    MessagePacket,
)
from core.module import PacketConsumerModule

logger = logging.getLogger(__name__)

_DEFAULT_FORMAT = "[{pipeline_name}] {text_original} → {text_translated}"

# 全局订阅者列表（GUI 用于接收实时输出）
_gui_callbacks: list[Callable[[str, str, str], None]] = []


def register_gui_callback(fn: Callable[[str, str, str], None]) -> None:
    """注册 GUI 回调。fn(pipeline_name, text_original, text_translated)"""
    _gui_callbacks.append(fn)


def unregister_gui_callback(fn: Callable[[str, str, str], None]) -> None:
    if fn in _gui_callbacks:
        _gui_callbacks.remove(fn)


class TerminalConsumer(PacketConsumerModule):
    """将翻译结果打印到标准输出。"""

    def __init__(self, module_id: str, config: dict) -> None:
        super().__init__(module_id, config)
        self._use_color: bool = config.get("color", True)
        self._fmt: str = config.get("format", _DEFAULT_FORMAT)
        self._pipeline_name: str = config.get("pipeline_name", config.get("pipeline_id", ""))

        if self._use_color:
            try:
                import colorama
                colorama.init(autoreset=True)
                self._colorama = colorama
            except ImportError:
                self._use_color = False
                self._colorama = None
        else:
            self._colorama = None

    def process_packet(self, packet: MessagePacket) -> list[MessagePacket]:

        original: str = packet.get(KEY_TEXT_ORIGINAL, "")
        translated: str = packet.get(KEY_TEXT_TRANSLATED, "")
        source_lang: str = packet.get(KEY_SOURCE_LANG, "")
        target_lang: str = packet.get(KEY_TARGET_LANG, "")

        if not original and not translated:
            return [packet]

        line = self._fmt.format(
            pipeline_name=self._pipeline_name,
            pipeline_id=self.config.get("pipeline_id", ""),
            text_original=original,
            text_translated=translated,
            source_lang=source_lang,
            target_lang=target_lang,
        )

        if packet.is_partial:
            self._print_partial(line)
        else:
            self._print_final(line)

        # 通知 GUI 回调
        for cb in _gui_callbacks:
            try:
                cb(self._pipeline_name, original, translated)
            except Exception:
                logger.debug("GUI 回调异常", exc_info=True)

        return [packet]

    def _print_final(self, line: str) -> None:
        if self._use_color and self._colorama:
            c = self._colorama
            print(f"{c.Fore.CYAN}{line}{c.Style.RESET_ALL}", flush=True)
        else:
            print(line, flush=True)

    def _print_partial(self, line: str) -> None:
        if self._use_color and self._colorama:
            c = self._colorama
            print(f"{c.Fore.YELLOW}{line}{c.Style.RESET_ALL}", flush=True)
        else:
            print(line, flush=True)

    