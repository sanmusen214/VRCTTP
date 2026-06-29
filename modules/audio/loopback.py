"""
LoopbackSource — 通过 soundcard 捕获系统扬声器环回音频。

Config 参数：
    device_name (str|null): 扬声器设备名，null 或“默认系统音频”使用系统默认音频输出
    sample_rate (int): 采样率，默认 16000
    vad_mode (int): VAD 灵敏度 0-3，默认 2
    sync_vrc_mic (bool): 是否跟随 VRChat 游戏内麦克风开关，默认 false

实现说明：
    使用 soundcard 枚举系统音频输出设备，再获取对应 WASAPI loopback 录音器。
"""

from __future__ import annotations

import logging
import warnings

import soundcard as sc

from core.module import ParamType
from modules.audio.base import FRAME_SAMPLES, TARGET_SAMPLE_RATE, VADPacketProducerModule
from modules.audio.sounddevice_backend import DEFAULT_SYSTEM_AUDIO_DEVICE

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=RuntimeWarning, module="soundcard")


class LoopbackSource(VADPacketProducerModule):
    """通过 soundcard 捕获系统扬声器环回音频输出。"""

    SOURCE_TYPE = "loopback"

    @classmethod
    def require_attributes_in_packages(cls) -> list[dict]:
        return []

    @classmethod
    def add_attributes_in_packages(cls) -> list[dict]:
        return [
            {"name": "audio_data",        "must_have": True,  "description": "16-bit PCM mono 音频字节"},
            {"name": "sample_rate",        "must_have": True,  "description": "采样率，如 16000"},
            {"name": "source_type",        "must_have": True,  "description": "来源类型：\"loopback\""},
            {"name": "source_name",        "must_have": True,  "description": "扬声器设备名"},
            {"name": "is_final_segment",   "must_have": True,  "description": "True 表示完整语音段"},
            {"name": "is_partial",         "must_have": True,  "description": "流式模式 True=中间块"},
            {"name": "is_speech_start",    "must_have": False, "description": "True 表示新语音段首帧"},
            {"name": "audio_chunk_idx",    "must_have": False, "description": "流式模式帧序号"},
            {"name": "timestamp",          "must_have": False, "description": "音频捕获 UTC 时间戳"},
        ]

    @classmethod
    def get_config_attributes(cls) -> list[dict]:
        return [
            {"name": "device_name",        "type": ParamType.String,   "default": DEFAULT_SYSTEM_AUDIO_DEVICE, "required": False, "description": "系统音频输出设备；默认系统音频表示 Windows 当前默认扬声器", "selectable": None, "options_loader": "loopback"},
            {"name": "sample_rate",        "type": ParamType.Int,      "default": 16000,       "required": False, "description": "采样率（Hz）", "selectable": None, "min": 8000, "max": 48000},
            {"name": "vad_mode",           "type": ParamType.Int,      "default": 2,           "required": False, "description": "VAD 灵敏度 0-3（3 最灵敏）", "selectable": None, "min": 0, "max": 3},
            {"name": "mode",               "type": ParamType.Select,   "default": "streaming", "required": False, "description": "工作模式", "selectable": ["batch", "streaming"]},
            {"name": "max_segment_seconds","type": ParamType.Float,    "default": 30.0,        "required": False, "description": "批处理模式最长分段（秒）", "selectable": None, "min": 1.0, "max": 120.0},
            {"name": "chunk_ms",           "type": ParamType.Int,      "default": 200,         "required": False, "description": "流式模式每块时长（ms）", "selectable": None, "min": 50, "max": 2000},
            {"name": "sync_vrc_mic",       "type": ParamType.Bool,     "default": False,       "required": False, "description": "仅在 VRChat 游戏内麦克风开启时向下游发送数据包（需启用 VRChat OSC）", "selectable": None},
        ]

    def _find_speaker(self):
        """
        按以下优先级查找扬声器设备：
        1. 配置指定的输出设备
        2. Windows 当前默认音频输出设备
        """
        device_name: str | None = self.config.get("device_name")
        if device_name and device_name != DEFAULT_SYSTEM_AUDIO_DEVICE:
            speaker = sc.get_speaker(id=device_name)
            logger.info("[%s] 使用指定系统音频输出: %s", self.module_id, speaker.name)
            return speaker

        speaker = sc.default_speaker()
        logger.info("[%s] 使用默认系统音频输出: %s", self.module_id, speaker.name)
        return speaker

    def _find_loopback_mic(self):
        speaker = self._find_speaker()
        try:
            return sc.get_microphone(id=speaker.name, include_loopback=True)
        except Exception:
            loopbacks = [m for m in sc.all_microphones(include_loopback=True) if m.isloopback]
            for mic in loopbacks:
                if mic.name.lower() in speaker.name.lower() or speaker.name.lower() in mic.name.lower():
                    return mic
            raise RuntimeError(f"找不到扬声器 '{speaker.name}' 对应的 soundcard loopback 录音设备。")

    def _create_recorder(self):
        mic = self._find_loopback_mic()
        sample_rate: int = self.config.get("sample_rate", TARGET_SAMPLE_RATE)
        logger.info("[%s] 使用 soundcard 扬声器环回: %s", self.module_id, mic.name)
        return mic.recorder(samplerate=sample_rate, blocksize=FRAME_SAMPLES)

    def _source_name(self) -> str:
        device_name = self.config.get("device_name")
        if device_name and device_name != DEFAULT_SYSTEM_AUDIO_DEVICE:
            return device_name
        return f"loopback:{sc.default_speaker().name}"
