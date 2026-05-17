"""
MicrophoneSource — 从系统麦克风采集音频。

Config 参数：
    device_name (str|null): 麦克风设备名，null 使用系统默认麦克风
    sample_rate (int): 采样率，默认 16000
    vad_mode (int): VAD 灵敏度 0-3，默认 2
"""

from __future__ import annotations

import logging
import warnings

import soundcard as sc

from modules.audio.base import FRAME_SAMPLES, TARGET_SAMPLE_RATE, VADPacketProducerModule

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=RuntimeWarning, module="soundcard")


class MicrophoneSource(VADPacketProducerModule):
    """从系统麦克风采集音频（不含环回）。"""

    SOURCE_TYPE = "microphone"

    def _create_recorder(self):
        """获取麦克风并创建录音器。"""
        device_name: str | None = self.config.get("device_name")
        sample_rate: int = self.config.get("sample_rate", TARGET_SAMPLE_RATE)

        if device_name:
            mic = sc.get_microphone(id=device_name, include_loopback=False)
        else:
            mic = sc.default_microphone()

        logger.info("[%s] 使用麦克风: %s", self.module_id, mic.name)
        return mic.recorder(samplerate=sample_rate, blocksize=FRAME_SAMPLES)

    def _source_name(self) -> str:
        device_name = self.config.get("device_name")
        if device_name:
            return device_name
        return sc.default_microphone().name
