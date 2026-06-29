"""
MicrophoneSource — 从系统麦克风采集音频。

Config 参数：
    device_name (str|null): 麦克风设备名，null 使用系统默认麦克风
    sample_rate (int): 采样率，默认 16000
    vad_mode (int): VAD 灵敏度 0-3，默认 2
    sync_vrc_mic (bool): 是否跟随 VRChat 游戏内麦克风开关，默认 false
"""

from __future__ import annotations

import logging

from core.module import ParamType
from modules.audio.base import FRAME_SAMPLES, TARGET_SAMPLE_RATE, VADPacketProducerModule
from modules.audio.sounddevice_backend import (
    SoundDeviceRecorder,
    default_input_device,
    find_input_device,
)

logger = logging.getLogger(__name__)


class MicrophoneSource(VADPacketProducerModule):
    """从系统麦克风采集音频（不含环回）。"""

    SOURCE_TYPE = "microphone"

    @classmethod
    def require_attributes_in_packages(cls) -> list[dict]:
        return []

    @classmethod
    def add_attributes_in_packages(cls) -> list[dict]:
        return [
            {"name": "audio_data",        "must_have": True,  "description": "16-bit PCM mono 音频字节"},
            {"name": "sample_rate",        "must_have": True,  "description": "采样率，如 16000"},
            {"name": "source_type",        "must_have": True,  "description": "来源类型：\"microphone\""},
            {"name": "source_name",        "must_have": True,  "description": "麦克风设备名"},
            {"name": "is_final_segment",   "must_have": True,  "description": "True 表示完整语音段"},
            {"name": "is_partial",         "must_have": True,  "description": "流式模式 True=中间块"},
            {"name": "is_speech_start",    "must_have": False, "description": "True 表示新语音段首帧"},
            {"name": "audio_chunk_idx",    "must_have": False, "description": "流式模式帧序号"},
            {"name": "timestamp",          "must_have": False, "description": "音频捕获 UTC 时间戳"},
        ]

    @classmethod
    def get_config_attributes(cls) -> list[dict]:
        return [
            {"name": "device_name",        "type": ParamType.String,   "default": None,        "required": False, "description": "麦克风设备名，null 使用系统默认", "selectable": None, "options_loader": "microphone"},
            {"name": "sample_rate",        "type": ParamType.Int,      "default": 16000,       "required": False, "description": "采样率（Hz）", "selectable": None, "min": 8000, "max": 48000},
            {"name": "vad_mode",           "type": ParamType.Int,      "default": 2,           "required": False, "description": "VAD 灵敏度 0-3（3 最灵敏）", "selectable": None, "min": 0, "max": 3},
            {"name": "mode",               "type": ParamType.Select,   "default": "streaming", "required": False, "description": "工作模式", "selectable": ["batch", "streaming"]},
            {"name": "max_segment_seconds","type": ParamType.Float,    "default": 30.0,        "required": False, "description": "批处理模式最长分段（秒）", "selectable": None, "min": 1.0, "max": 120.0},
            {"name": "chunk_ms",           "type": ParamType.Int,      "default": 200,         "required": False, "description": "流式模式每块时长（ms）", "selectable": None, "min": 50, "max": 2000},
            {"name": "sync_vrc_mic",       "type": ParamType.Bool,     "default": False,       "required": False, "description": "仅在 VRChat 游戏内麦克风开启时向下游发送数据包（需启用 VRChat OSC）", "selectable": None},
        ]

    def _create_recorder(self):
        """获取麦克风并创建录音器。"""
        device_name: str | None = self.config.get("device_name")
        sample_rate: int = self.config.get("sample_rate", TARGET_SAMPLE_RATE)

        mic = find_input_device(device_name)
        logger.info("[%s] 使用麦克风: %s", self.module_id, mic.name)
        return SoundDeviceRecorder(mic, samplerate=sample_rate, blocksize=FRAME_SAMPLES)

    def _source_name(self) -> str:
        device_name = self.config.get("device_name")
        if device_name:
            return device_name
        return default_input_device().name
