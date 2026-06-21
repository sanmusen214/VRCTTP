"""
LoopbackSource — 通过系统音频环回捕获指定进程（或系统默认）的音频。

Config 参数：
    process_name (str|null): 目标进程名（如 "VRChat.exe"），null 使用系统默认扬声器环回
    sample_rate (int): 采样率，默认 16000
    vad_mode (int): VAD 灵敏度 0-3，默认 2
    sync_vrc_mic (bool): 是否跟随 VRChat 游戏内麦克风开关，默认 false

实现说明：
    遍历 soundcard 的 all_microphones(include_loopback=True)，
    找到名称中包含 process_name 的回环设备；若找不到则退回到默认扬声器环回。
    与 music_freq_utils.py 中的 _get_loopback_mic() 模式一致。
"""

from __future__ import annotations

import logging
import warnings

import soundcard as sc

from core.module import ParamType
from modules.audio.base import FRAME_SAMPLES, TARGET_SAMPLE_RATE, VADPacketProducerModule

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=RuntimeWarning, module="soundcard")


class LoopbackSource(VADPacketProducerModule):
    """通过 WASAPI 环回捕获指定进程（或系统扬声器）的音频输出。"""

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
            {"name": "source_name",        "must_have": True,  "description": "目标进程名或设备名"},
            {"name": "is_final_segment",   "must_have": True,  "description": "True 表示完整语音段"},
            {"name": "is_partial",         "must_have": True,  "description": "流式模式 True=中间块"},
            {"name": "is_speech_start",    "must_have": False, "description": "True 表示新语音段首帧"},
            {"name": "audio_chunk_idx",    "must_have": False, "description": "流式模式帧序号"},
            {"name": "timestamp",          "must_have": False, "description": "音频捕获 UTC 时间戳"},
        ]

    @classmethod
    def get_config_attributes(cls) -> list[dict]:
        return [
            {"name": "process_name",       "type": ParamType.String,   "default": None,        "required": False, "description": "目标进程名（如 \"VRChat.exe\"），null 捕获系统扬声器", "selectable": None},
            {"name": "sample_rate",        "type": ParamType.Int,      "default": 16000,       "required": False, "description": "采样率（Hz）", "selectable": None, "min": 8000, "max": 48000},
            {"name": "vad_mode",           "type": ParamType.Int,      "default": 2,           "required": False, "description": "VAD 灵敏度 0-3（3 最灵敏）", "selectable": None, "min": 0, "max": 3},
            {"name": "mode",               "type": ParamType.Select,   "default": "streaming", "required": False, "description": "工作模式", "selectable": ["batch", "streaming"]},
            {"name": "max_segment_seconds","type": ParamType.Float,    "default": 30.0,        "required": False, "description": "批处理模式最长分段（秒）", "selectable": None, "min": 1.0, "max": 120.0},
            {"name": "chunk_ms",           "type": ParamType.Int,      "default": 200,         "required": False, "description": "流式模式每块时长（ms）", "selectable": None, "min": 50, "max": 2000},
            {"name": "sync_vrc_mic",       "type": ParamType.Bool,     "default": False,       "required": False, "description": "仅在 VRChat 游戏内麦克风开启时向下游发送数据包（需启用 VRChat OSC）", "selectable": None},
        ]

    def _find_loopback_mic(self):
        """
        按以下优先级查找环回设备：
        1. 名称包含 process_name 的 loopback 麦克风（进程音频隔离）
        2. 系统默认扬声器对应的 loopback 麦克风（通过名称匹配 get_microphone）
        3. 任意第一个 loopback 设备
        注意：sc.default_speaker() 返回 _Speaker 对象，没有 .recorder()，
        必须通过 get_microphone(include_loopback=True) 拿到可录音的 loopback mic。
        """
        process_name: str | None = self.config.get("process_name")

        all_mics = sc.all_microphones(include_loopback=True)
        loopback_mics = [m for m in all_mics if m.isloopback]

        if process_name:
            pname_lower = process_name.lower().removesuffix(".exe")
            # 进程名匹配（不区分大小写）
            matched = [m for m in loopback_mics if pname_lower in m.name.lower()]
            if matched:
                logger.info("[%s] 找到进程环回设备: %s", self.module_id, matched[0].name)
                return matched[0]
            logger.warning(
                "[%s] 未找到进程 '%s' 的环回设备，退回到默认扬声器环回",
                self.module_id, process_name,
            )

        # 退路：使用系统当前默认扬声器的环回
        # sc.default_speaker() 返回 _Speaker 对象，没有 .recorder()，
        # 需通过 get_microphone(include_loopback=True) 拿到对应的 loopback mic 对象
        try:
            default_speaker = sc.default_speaker()
            mic = sc.get_microphone(id=default_speaker.name, include_loopback=True)
            logger.info("[%s] 使用默认扬声器环回: %s", self.module_id, mic.name)
            return mic
        except Exception:
            pass

        # 最后退路：任意 loopback 设备
        if loopback_mics:
            logger.info("[%s] 使用第一个可用环回设备: %s", self.module_id, loopback_mics[0].name)
            return loopback_mics[0]

        raise RuntimeError(
            "未找到任何环回音频设备。请确认系统支持音频环回，且已安装相应驱动。"
        )

    def _create_recorder(self):
        device = self._find_loopback_mic()
        sample_rate: int = self.config.get("sample_rate", TARGET_SAMPLE_RATE)
        return device.recorder(samplerate=sample_rate, blocksize=FRAME_SAMPLES)

    def _source_name(self) -> str:
        process_name = self.config.get("process_name")
        if process_name:
            return process_name
        return f"loopback:{sc.default_speaker().name}"
