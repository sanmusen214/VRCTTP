from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from core.packet import KEY_AUDIO_DATA, KEY_IS_FINAL_SEGMENT
from modules.audio.base import FRAME_BYTES, TARGET_SAMPLE_RATE, VADPacketProducerModule


class _FakeVad:
    def __init__(self, speech_flags: list[bool]) -> None:
        self._speech_flags = speech_flags
        self._index = 0

    def is_speech(self, _frame: bytes, _sample_rate: int) -> bool:
        if self._index >= len(self._speech_flags):
            return False
        value = self._speech_flags[self._index]
        self._index += 1
        return value


class _FakeRecorder:
    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        return None

    def record(self, numframes: int) -> np.ndarray:
        return np.zeros(numframes, dtype=np.float32)


class _FakeVRCMicMonitor:
    def __init__(self) -> None:
        self._calls = 0

    def is_mic_open(self) -> bool:
        self._calls += 1
        return self._calls == 1


class _TestAudioSource(VADPacketProducerModule):
    SOURCE_TYPE = "test"

    @classmethod
    def require_attributes_in_packages(cls) -> list[dict]:
        return []

    @classmethod
    def add_attributes_in_packages(cls) -> list[dict]:
        return []

    @classmethod
    def get_config_attributes(cls) -> list[dict]:
        return []

    def _create_recorder(self):
        return _FakeRecorder()

    def _source_name(self) -> str:
        return "fake"


class VRCMicSyncVADTest(unittest.TestCase):
    def test_batch_segment_started_while_vrc_mic_open_is_emitted_after_close(self) -> None:
        source = _TestAudioSource(
            "test.audio",
            {
                "pipeline_id": "pipeline",
                "mode": "batch",
                "sample_rate": TARGET_SAMPLE_RATE,
                "sync_vrc_mic": True,
            },
        )
        source._vad = _FakeVad([True] * 15 + [False] * 15)
        monitor = _FakeVRCMicMonitor()

        with patch("modules.audio.base.vrc_mic_state_monitor", monitor):
            packet = next(source.produce_packets())

        self.assertTrue(packet.get(KEY_IS_FINAL_SEGMENT))
        self.assertEqual(len(packet.get(KEY_AUDIO_DATA)), 30 * FRAME_BYTES)


if __name__ == "__main__":
    unittest.main()
