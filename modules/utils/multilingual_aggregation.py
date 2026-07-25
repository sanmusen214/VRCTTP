"""多语言翻译包聚合工具。

同一句原文经过 DAG 分叉后会产生多个目标语言包。该模块保存一个短窗口，
按 ``group_by`` 时间戳找出最新一组，并在该管道的目标语言全部到齐后返回结果。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.packet import (
    KEY_TARGET_LANG,
    KEY_TEXT_ORIGINAL,
    KEY_TEXT_TRANSLATED,
    MessagePacket,
)


@dataclass(frozen=True)
class AggregatedTranslation:
    """一组已到齐、可供输出消费者渲染的翻译结果。"""

    pipeline_id: str | None
    group_value: Any
    original: str
    translated: str
    translations: dict[str, str]

    @property
    def display_key(self) -> tuple[str | None, Any]:
        """供 UI 原地更新同一完整句子的稳定标识。"""
        return (self.pipeline_id, self.group_value)


class MultilingualPacketAggregator:
    """维护最近的数据包并聚合最新一组多语言翻译。"""

    def __init__(self, group_by: str = "", history_size: int = 10) -> None:
        self.group_by = group_by
        self.history_size = max(1, int(history_size))
        self.last_any_packages: list[MessagePacket] = []
        self.last_translated_packages: list[MessagePacket] = []

    def add(self, packet: MessagePacket) -> AggregatedTranslation | None:
        """加入一个包；最新组尚未收齐所有已知语言时返回 ``None``。"""
        self._append_limited(self.last_any_packages, packet)
        if packet.get(KEY_TEXT_TRANSLATED) and packet.get(KEY_TARGET_LANG):
            self._append_limited(self.last_translated_packages, packet)

        original = (
            self.last_any_packages[-1].get(KEY_TEXT_ORIGINAL, "")
            if self.last_any_packages
            else ""
        )

        latest_group_value = self._latest_group_value()
        latest_packets = [
            item
            for item in reversed(self.last_translated_packages)
            if item.get(KEY_TARGET_LANG)
            and item.get(KEY_TEXT_TRANSLATED)
            and self._group_value(item) == latest_group_value
        ]

        focus_pipeline_id = latest_packets[-1].pipeline_id if latest_packets else None
        translations: dict[str, str] = {}
        for item in latest_packets:
            language = item.get(KEY_TARGET_LANG)
            translated = item.get(KEY_TEXT_TRANSLATED)
            if language and translated:
                translations[str(language)] = str(translated)

        existing_languages = {
            str(item.get(KEY_TARGET_LANG))
            for item in self.last_translated_packages
            if item.get(KEY_TARGET_LANG)
            and item.get(KEY_TEXT_TRANSLATED)
            and item.pipeline_id == focus_pipeline_id
        }
        ordered_languages = sorted(existing_languages)
        if ordered_languages and any(lang not in translations for lang in ordered_languages):
            return None

        translated_text = "\n".join(
            translations[lang] for lang in ordered_languages if lang in translations
        )
        return AggregatedTranslation(
            pipeline_id=focus_pipeline_id,
            group_value=latest_group_value,
            original=str(original or ""),
            translated=translated_text,
            translations={lang: translations[lang] for lang in ordered_languages},
        )

    def _latest_group_value(self) -> Any:
        latest = None
        for packet in reversed(self.last_translated_packages):
            value = self._group_value(packet)
            if value is not None and (latest is None or value > latest):
                latest = value
        return latest

    def _group_value(self, packet: MessagePacket) -> Any:
        """显式 group_by 为空时，使用分叉克隆共享的创建时间自动分句。"""
        if self.group_by:
            return packet.get(self.group_by)
        return packet.created_at

    def _append_limited(
        self, target: list[MessagePacket], packet: MessagePacket
    ) -> None:
        target.append(packet)
        if len(target) > self.history_size:
            target.pop(0)
