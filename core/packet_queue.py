"""管道输入队列策略。"""

from __future__ import annotations

import logging
import queue
from typing import Any

from core.packet import (
    KEY_AUDIO_CHUNK_END_INDEX,
    KEY_AUDIO_CHUNK_INDEX,
    KEY_AUDIO_DATA,
    KEY_IS_FINAL_SEGMENT,
    KEY_IS_PARTIAL,
    KEY_IS_SPEECH_START,
    KEY_SAMPLE_RATE,
    MessagePacket,
)

logger = logging.getLogger(__name__)


class CoalescingStreamingAudioQueue(queue.Queue):
    """将拥塞时同一语音段的相邻 PCM 包按顺序合并。

    ``maxsize`` 是开始合并的软阈值，不是丢包上限。语音段边界不能安全
    合并时允许队列动态扩容，以保留 final/start 顺序。
    """

    def __init__(self, maxsize: int = 0, warning_seconds: float = 3.0) -> None:
        super().__init__(maxsize=maxsize)
        self._warning_seconds = max(0.0, float(warning_seconds))
        self._next_warning_seconds = self._warning_seconds

    def put_nowait(self, item: MessagePacket | None) -> None:
        with self.not_full:
            if item is not None and self.maxsize > 0 and self._qsize() >= self.maxsize:
                tail = self.queue[-1] if self.queue else None
                if isinstance(tail, MessagePacket) and self._can_coalesce(tail, item):
                    self._coalesce(tail, item)
                    self._warn_if_backlogged(tail)
                    self.not_empty.notify()
                    return

            # 边界包或哨兵不丢弃；超过软阈值时动态增长。
            self._put(item)
            self.unfinished_tasks += 1
            self.not_empty.notify()

    @staticmethod
    def _can_coalesce(tail: MessagePacket, incoming: MessagePacket) -> bool:
        return (
            tail.pipeline_id == incoming.pipeline_id
            and isinstance(tail.get(KEY_AUDIO_DATA), bytes)
            and isinstance(incoming.get(KEY_AUDIO_DATA), bytes)
            and not tail.get(KEY_IS_FINAL_SEGMENT, False)
            and not incoming.get(KEY_IS_SPEECH_START, False)
        )

    @staticmethod
    def _coalesce(tail: MessagePacket, incoming: MessagePacket) -> None:
        tail.set(
            KEY_AUDIO_DATA,
            tail.get(KEY_AUDIO_DATA, b"") + incoming.get(KEY_AUDIO_DATA, b""),
        )
        incoming_end = incoming.get(
            KEY_AUDIO_CHUNK_END_INDEX,
            incoming.get(KEY_AUDIO_CHUNK_INDEX),
        )
        if incoming_end is not None:
            tail.set(KEY_AUDIO_CHUNK_END_INDEX, incoming_end)
        tail.set(KEY_IS_FINAL_SEGMENT, incoming.get(KEY_IS_FINAL_SEGMENT, False))
        tail.set(KEY_IS_PARTIAL, incoming.get(KEY_IS_PARTIAL, incoming.is_partial))
        tail.is_partial = incoming.is_partial

    def _warn_if_backlogged(self, packet: MessagePacket) -> None:
        if self._next_warning_seconds <= 0:
            return
        sample_rate = int(packet.get(KEY_SAMPLE_RATE, 16000) or 16000)
        seconds = len(packet.get(KEY_AUDIO_DATA, b"")) / (sample_rate * 2)
        if seconds < self._next_warning_seconds:
            return
        logger.warning(
            "本地流式 STT 音频积压 %.2fs，已按时间顺序合并缓冲；"
            "若持续增长，说明模型推理速度低于实时速度",
            seconds,
        )
        self._next_warning_seconds *= 2


def create_packet_queue(
    policy: str,
    *,
    maxsize: int,
    options: dict[str, Any] | None = None,
) -> queue.Queue:
    """按声明策略创建队列。"""
    options = options or {}
    if policy == "coalesce_streaming_audio":
        return CoalescingStreamingAudioQueue(
            maxsize=maxsize,
            warning_seconds=float(options.get("warning_seconds", 3.0)),
        )
    if policy == "drop_oldest":
        return queue.Queue(maxsize=maxsize)
    raise ValueError(f"未知队列策略: {policy!r}")
