"""
LoopbackSource — 通过系统音频环回捕获指定进程（或系统默认）的音频。

Config 参数：
    process_name (str|null): 目标进程名（如 "VRChat.exe"），null 使用系统默认扬声器环回
    sample_rate (int): 采样率，默认 16000
    vad_mode (int): VAD 灵敏度 0-3，默认 2

实现说明：
    遍历 soundcard 的 all_microphones(include_loopback=True)，
    找到名称中包含 process_name 的回环设备；若找不到则退回到默认扬声器环回。
    与 music_freq_utils.py 中的 _get_loopback_mic() 模式一致。
"""

from __future__ import annotations

import logging
import warnings

import soundcard as sc

from modules.audio.base import FRAME_SAMPLES, TARGET_SAMPLE_RATE, VADPacketProducerModule

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=RuntimeWarning, module="soundcard")


class LoopbackSource(VADPacketProducerModule):
    """通过 WASAPI 环回捕获指定进程（或系统扬声器）的音频输出。"""

    SOURCE_TYPE = "loopback"

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
