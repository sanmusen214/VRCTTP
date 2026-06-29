"""
PacketProducerModule 基类 — 包含 VAD（语音活动检测）共享逻辑。

支持两种工作模式（通过 config['mode'] 配置）：

【批处理模式 mode="batch"（默认）】
  1. 以 30ms 帧为单位处理音频
  2. 用 300ms 滑动窗口（前补丁）判断语音开始：窗口内 ≥75% 为有声帧 → 触发开始
  3. 积累语音帧 + 结束填充：结束窗口内 ≥75% 为无声帧 → 触发结束
  4. 分段完成后生成 IS_FINAL_SEGMENT=True 的 MessagePacket
  5. 智能超长截断：当语音超过 max_segment_seconds 时，用更宽松的 VAD 在
     缓冲区中找到最近的自然停顿点，从该点拆分：前段作为一个包发出，
     后段保留在缓冲区继续积累（不丢弃）。

【流式模式 mode="streaming"】
  1. 使用 VAD 跟踪语音状态
  2. 语音期间持续emit小块（chunk_ms 毫秒，默认 200ms）音频包：
       is_partial=True，is_final_segment=False，is_speech_start=True（首块）
  3. VAD 检测到静音后，将剩余音频emit为最终包：
       is_partial=False，is_final_segment=True
  流式模式适合配合流式 STT 模块（如 VolcStreamingSTT）使用，
  可在语音段结束前就开始处理，降低端到端延迟。

子类只需提供带 record(numframes) 方法的录音器，无需关心 VAD 逻辑。
"""

from __future__ import annotations

import collections
import logging
import time
from abc import abstractmethod

import numpy as np
import webrtcvad

from core.module import PacketProducerModule as PacketProducerModule
from core.packet import (
    KEY_AUDIO_CHUNK_INDEX,
    KEY_AUDIO_DATA,
    KEY_IS_FINAL_SEGMENT,
    KEY_IS_PARTIAL,
    KEY_IS_SPEECH_START,
    KEY_SAMPLE_RATE,
    KEY_SOURCE_NAME,
    KEY_SOURCE_TYPE,
    KEY_TIMESTAMP,
    MessagePacket,
)
from modules.audio.vrc_mic_state import vrc_mic_state_monitor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

TARGET_SAMPLE_RATE = 16000       # webrtcvad 要求 8/16/32/48 kHz
FRAME_DURATION_MS = 30           # 30ms 每帧（webrtcvad 支持 10/20/30ms）
FRAME_SAMPLES = TARGET_SAMPLE_RATE * FRAME_DURATION_MS // 1000  # = 480 samples
FRAME_BYTES = FRAME_SAMPLES * 2  # int16 = 2 bytes/sample

PADDING_DURATION_MS = 450        # 前/后补丁窗口长度（加长以减少短促误触发）
PADDING_FRAMES = PADDING_DURATION_MS // FRAME_DURATION_MS  # = 15 frames
PRE_START_RETAIN_FRAMES = PADDING_FRAMES  # 保留触发前的额外帧（即额外采纳上一个判断周期）

START_RATIO = 0.85   # 窗口中有声帧比例 >= 此值 -> 语音开始
END_RATIO = 0.8      # 无声帧比例 >= 此值 -> 语音结束

DEFAULT_MAX_SEGMENT_SECONDS = 15  # 默认最大片段时长
DEFAULT_CHUNK_MS = 200            # 流式模式下每包音频时长（ms）


def _resample(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """重采样（优先用 scipy，退路用 numpy 插值）。"""
    if orig_sr == target_sr:
        return audio
    try:
        from math import gcd
        from scipy.signal import resample_poly
        g = gcd(orig_sr, target_sr)
        return resample_poly(audio, target_sr // g, orig_sr // g)
    except ImportError:
        n_samples = int(len(audio) * target_sr / orig_sr)
        return np.interp(
            np.linspace(0, len(audio) - 1, n_samples),
            np.arange(len(audio)),
            audio,
        )


class VADPacketProducerModule(PacketProducerModule):
    """
    带 VAD 的音频源基类。

    Config 参数（子类可扩展）：
        mode (str): "batch"（默认）或 "streaming"
        sample_rate (int): 采集采样率，默认 16000
        vad_mode (int): webrtcvad 灵敏度 0-3，默认 2
        max_segment_seconds (float): 单段最大录音秒数，默认 15
            超过此时长后（批处理模式）会触发智能截断
        chunk_ms (int): 流式模式下每个音频包的时长（ms），默认 200
        sync_vrc_mic (bool): 是否仅在 VRChat 麦克风开启时向下游发包
    """

    SOURCE_TYPE: str = "base"  # 子类覆盖

    def __init__(self, module_id: str, config: dict) -> None:
        super().__init__(module_id, config)
        self._sample_rate: int = config.get("sample_rate", TARGET_SAMPLE_RATE)
        self._vad_mode: int = config.get("vad_mode", 2)
        self._vad = webrtcvad.Vad(self._vad_mode)
        self._max_segment_seconds: float = config.get("max_segment_seconds", DEFAULT_MAX_SEGMENT_SECONDS)
        self._mode: str = config.get("mode", "batch")
        self._chunk_ms: int = int(config.get("chunk_ms", DEFAULT_CHUNK_MS))
        self._sync_vrc_mic: bool = bool(config.get("sync_vrc_mic", False))
        self._vrc_monitor_acquired = False
        self._last_vrc_mic_state: bool | None = None
        self._vrc_mic_state_logged = False

    def on_start(self) -> None:
        if self._sync_vrc_mic:
            logger.info(
                "[%s] VRChat 麦克风状态同步已启用，准备启动 OSC 监听",
                self.module_id,
            )
            vrc_mic_state_monitor.acquire()
            self._vrc_monitor_acquired = True
        else:
            logger.info(
                "[%s] VRChat 麦克风状态同步未启用（sync_vrc_mic=false）",
                self.module_id,
            )

    def on_after_stop(self) -> None:
        if self._vrc_monitor_acquired:
            vrc_mic_state_monitor.release()
            self._vrc_monitor_acquired = False

    # ------------------------------------------------------------------
    # 子类须实现
    # ------------------------------------------------------------------

    @abstractmethod
    def _create_recorder(self):
        """创建并返回 recorder context manager。"""

    @abstractmethod
    def _source_name(self) -> str:
        """返回音频源的可读名称。"""

    # ------------------------------------------------------------------
    # 生产包（PacketProducerModule 接口）
    # ------------------------------------------------------------------

    def produce_packets(self):
        """根据 mode 派发到对应的内部循环。"""
        pipeline_id: str = self.config.get("pipeline_id", "unknown")
        source_name = self._source_name()
        logger.info("[%s] 开始捕获音频（mode=%s）: %s", self.module_id, self._mode, source_name)

        while not self._stop_event.is_set():
            try:
                recorder = self._create_recorder()
                with recorder as r:
                    packets = (
                        self._streaming_loop(r, pipeline_id, source_name)
                        if self._mode == "streaming"
                        else self._batch_loop(r, pipeline_id, source_name)
                    )
                    for packet in packets:
                        if self._vrc_mic_allows_output():
                            yield packet
            except Exception:
                if not self._stop_event.is_set():
                    logger.exception("[%s] 录音器出错，1秒后重试", self.module_id)
                    time.sleep(1)

    def _vrc_mic_allows_output(self) -> bool:
        if not self._sync_vrc_mic:
            return True
        state = vrc_mic_state_monitor.is_mic_open()
        if not self._vrc_mic_state_logged or state != self._last_vrc_mic_state:
            if state is None:
                logger.warning(
                    "[%s] 尚未收到 VRChat 麦克风状态，暂不向下游发送音频包",
                    self.module_id,
                )
            else:
                logger.info(
                    "[%s] VRChat 麦克风%s，%s向下游发送音频包",
                    self.module_id,
                    "开启" if state else "关闭",
                    "恢复" if state else "暂停",
                )
            self._last_vrc_mic_state = state
            self._vrc_mic_state_logged = True
        return state is True

    # ------------------------------------------------------------------
    # 批处理 VAD 主循环（含智能超长截断）
    # ------------------------------------------------------------------

    def _batch_loop(self, recorder, pipeline_id: str, source_name: str):
        """
        批处理模式：完整语音段结束后才 yield 包。

        超长截断逻辑：
          当 voiced_buffer 超过 max_segment_seconds 时，用更宽松的 VAD
          向前搜索最近的自然停顿点，从该点拆分：
            - 停顿前的内容 → emit 作为一个完整包
            - 停顿后的内容 → 保留在 voiced_buffer 继续积累（triggered=True）
        """
        max_frames = int(self._max_segment_seconds * 1000 / FRAME_DURATION_MS)

        ring = collections.deque(maxlen=PADDING_FRAMES + PRE_START_RETAIN_FRAMES)  # 语音开始检测环形缓冲 + 上一个窗口
        voiced_buffer: list[bytes] = []
        triggered = False
        end_padding: list[bool] = []
        leftover_pcm = b""

        while not self._stop_event.is_set():
            raw: np.ndarray = recorder.record(numframes=FRAME_SAMPLES)

            if raw.ndim == 2:
                raw = raw.mean(axis=1)
            if self._sample_rate != TARGET_SAMPLE_RATE:
                raw = _resample(raw, self._sample_rate, TARGET_SAMPLE_RATE)

            chunk = (np.clip(raw, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
            data = leftover_pcm + chunk
            frames = []
            offset = 0
            while offset + FRAME_BYTES <= len(data):
                frames.append(data[offset: offset + FRAME_BYTES])
                offset += FRAME_BYTES
            leftover_pcm = data[offset:]

            for frame in frames:
                try:
                    is_speech = self._vad.is_speech(frame, TARGET_SAMPLE_RATE)
                except Exception:
                    is_speech = False

                if not triggered:
                    ring.append((frame, is_speech))
                    
                    recent_frames = list(ring)[-PADDING_FRAMES:]
                    num_voiced = sum(1 for _, s in recent_frames if s)
                    
                    if len(recent_frames) == PADDING_FRAMES and num_voiced / PADDING_FRAMES >= START_RATIO:
                        triggered = True
                        voiced_buffer = [f for f, _ in ring]
                        ring.clear()
                        end_padding.clear()
                        logger.info("[%s] 检测到人声（批处理模式）", self.module_id)
                else:
                    voiced_buffer.append(frame)
                    end_padding.append(is_speech)

                    # ── 超长截断（智能分割）────────────────────────────
                    if len(voiced_buffer) >= max_frames:
                        cut = self._find_cut_point(voiced_buffer)
                        if cut > 0:
                            # 前段 → emit；后段保留（triggered 不变）
                            first_pcm = b"".join(voiced_buffer[:cut])
                            voiced_buffer = voiced_buffer[cut:]
                            end_padding.clear()
                            dur = len(first_pcm) / (TARGET_SAMPLE_RATE * 2)
                            logger.info(
                                "[%s] 智能截断: 发出前 %.1fs，剩余 %.1fs 继续积累",
                                self.module_id, dur,
                                len(voiced_buffer) * FRAME_DURATION_MS / 1000,
                            )
                            yield self._build_batch_packet(pipeline_id, source_name, first_pcm)
                        else:
                            # 找不到截断点，强制发出全部
                            logger.warning(
                                "[%s] 超长 %.1fs 且找不到截断点，强制分割",
                                self.module_id, self._max_segment_seconds,
                            )
                            segment_pcm = b"".join(voiced_buffer)
                            voiced_buffer = []
                            end_padding.clear()
                            triggered = False
                            yield self._build_batch_packet(pipeline_id, source_name, segment_pcm)
                        continue  # 跳过下面的正常结束检测，避免重复处理

                    # ── 正常结束检测 ──────────────────────────────────
                    if len(end_padding) >= PADDING_FRAMES:
                        recent = end_padding[-PADDING_FRAMES:]
                        num_unvoiced = sum(1 for s in recent if not s)
                        if num_unvoiced / PADDING_FRAMES >= END_RATIO:
                            triggered = False
                            segment_pcm = b"".join(voiced_buffer)
                            voiced_buffer = []
                            end_padding.clear()
                            yield self._build_batch_packet(pipeline_id, source_name, segment_pcm)

    def _find_cut_point(self, frames: list[bytes]) -> int:
        """
        在超长语音缓冲区中，用更宽松的 VAD 向后（从末尾向前）搜索
        最近的自然停顿点，返回截断帧索引（0 表示找不到）。

        策略：从末尾向前扫描，找到连续 WINDOW 帧均被宽松 VAD 判为
        无声的窗口，截断点为该窗口结束处。搜索范围限制在前 3/4 内
        （确保至少保留 1/4 音频作为下一段的开头）。
        """
        lower_mode = max(0, self._vad_mode - 2)
        looser_vad = webrtcvad.Vad(lower_mode)

        WINDOW = max(3, PADDING_FRAMES // 3)   # ≈ 90ms 静音窗口
        search_limit = len(frames) * 3 // 4    # 只在前 3/4 范围内找截断点
        min_cut = len(frames) // 6             # 最少保留 1/6

        # 从 search_limit 向前（向头部）扫描
        for i in range(search_limit - WINDOW, min_cut, -1):
            window = frames[i: i + WINDOW]
            all_silence = all(
                not _safe_is_speech(looser_vad, f) for f in window
            )
            if all_silence:
                return i + WINDOW  # 截断点在静音窗口结束处
        return 0

    # ------------------------------------------------------------------
    # 流式模式主循环
    # ------------------------------------------------------------------

    def _streaming_loop(self, recorder, pipeline_id: str, source_name: str):
        """
        流式模式：语音期间持续 emit 小块音频包（IS_PARTIAL=True），
        VAD 检测到语音结束后 emit 最终标记包（IS_FINAL_SEGMENT=True）。

        包结构：
          - 首块: is_partial=True, is_final_segment=False, is_speech_start=True
          - 中间块: is_partial=True, is_final_segment=False
          - 末包: is_partial=False, is_final_segment=True（含最后音频或为空）
        """
        chunk_frames = max(1, self._chunk_ms // FRAME_DURATION_MS)

        ring = collections.deque(maxlen=PADDING_FRAMES + PRE_START_RETAIN_FRAMES)
        frame_buffer: list[bytes] = []   # 当前块积累的帧
        end_padding: list[bool] = []
        triggered = False
        chunk_idx = 0
        is_first_chunk = False
        leftover_pcm = b""

        while not self._stop_event.is_set():
            raw: np.ndarray = recorder.record(numframes=FRAME_SAMPLES)

            if raw.ndim == 2:
                raw = raw.mean(axis=1)
            if self._sample_rate != TARGET_SAMPLE_RATE:
                raw = _resample(raw, self._sample_rate, TARGET_SAMPLE_RATE)

            chunk = (np.clip(raw, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
            data = leftover_pcm + chunk
            frames = []
            offset = 0
            while offset + FRAME_BYTES <= len(data):
                frames.append(data[offset: offset + FRAME_BYTES])
                offset += FRAME_BYTES
            leftover_pcm = data[offset:]

            for frame in frames:
                try:
                    is_speech = self._vad.is_speech(frame, TARGET_SAMPLE_RATE)
                except Exception:
                    is_speech = False

                if not triggered:
                    ring.append((frame, is_speech))
                    
                    recent_frames = list(ring)[-PADDING_FRAMES:]
                    num_voiced = sum(1 for _, s in recent_frames if s)
                    
                    if len(recent_frames) == PADDING_FRAMES and num_voiced / PADDING_FRAMES >= START_RATIO:
                        # 语音开始
                        triggered = True
                        is_first_chunk = True
                        chunk_idx = 0
                        frame_buffer = [f for f, _ in ring]
                        ring.clear()
                        end_padding.clear()
                        logger.info("[%s] 检测到人声（流式模式）", self.module_id)
                else:
                    frame_buffer.append(frame)
                    end_padding.append(is_speech)

                    # 每积满 chunk_frames 帧就 emit 一个流式包
                    if len(frame_buffer) >= chunk_frames:
                        emit_frames = frame_buffer[:chunk_frames]
                        frame_buffer = frame_buffer[chunk_frames:]
                        pcm = b"".join(emit_frames)
                        yield self._build_streaming_chunk(
                            pipeline_id, source_name, pcm,
                            chunk_idx=chunk_idx,
                            is_speech_start=is_first_chunk,
                        )
                        chunk_idx += 1
                        is_first_chunk = False

                    # 结束检测
                    if len(end_padding) >= PADDING_FRAMES:
                        recent = end_padding[-PADDING_FRAMES:]
                        num_unvoiced = sum(1 for s in recent if not s)
                        if num_unvoiced / PADDING_FRAMES >= END_RATIO:
                            triggered = False
                            # 剩余帧作为最终包发出
                            remaining = b"".join(frame_buffer)
                            frame_buffer = []
                            end_padding.clear()
                            yield self._build_streaming_final(
                                pipeline_id, source_name, remaining
                            )

    # ------------------------------------------------------------------
    # 包构建辅助
    # ------------------------------------------------------------------

    def _base_packet(self, pipeline_id: str, source_name: str) -> MessagePacket:
        p = MessagePacket(pipeline_id=pipeline_id)
        p.set(KEY_SAMPLE_RATE, TARGET_SAMPLE_RATE)
        p.set(KEY_SOURCE_TYPE, self.SOURCE_TYPE)
        p.set(KEY_SOURCE_NAME, source_name)
        p.set(KEY_TIMESTAMP, time.time())
        return p

    def _build_batch_packet(self, pipeline_id: str, source_name: str, pcm_bytes: bytes) -> MessagePacket:
        """批处理模式：完整语音段包。"""
        p = self._base_packet(pipeline_id, source_name)
        p.is_partial = False
        p.set(KEY_AUDIO_DATA, pcm_bytes)
        p.set(KEY_IS_FINAL_SEGMENT, True)
        p.set(KEY_IS_PARTIAL, False)
        dur = len(pcm_bytes) / (TARGET_SAMPLE_RATE * 2)
        logger.debug("[%s] 生成批处理包: %.2fs", self.module_id, dur)
        return p

    def _build_streaming_chunk(
        self,
        pipeline_id: str,
        source_name: str,
        pcm_bytes: bytes,
        chunk_idx: int,
        is_speech_start: bool,
    ) -> MessagePacket:
        """流式模式：中间音频块包。"""
        p = self._base_packet(pipeline_id, source_name)
        p.is_partial = True
        p.set(KEY_AUDIO_DATA, pcm_bytes)
        p.set(KEY_IS_FINAL_SEGMENT, False)
        p.set(KEY_IS_PARTIAL, True)
        p.set(KEY_IS_SPEECH_START, is_speech_start)
        p.set(KEY_AUDIO_CHUNK_INDEX, chunk_idx)
        return p

    def _build_streaming_final(
        self,
        pipeline_id: str,
        source_name: str,
        remaining_pcm: bytes,
    ) -> MessagePacket:
        """流式模式：最终包（语音段结束信号）。"""
        p = self._base_packet(pipeline_id, source_name)
        p.is_partial = False
        p.set(KEY_AUDIO_DATA, remaining_pcm)
        p.set(KEY_IS_FINAL_SEGMENT, True)
        p.set(KEY_IS_PARTIAL, False)
        p.set(KEY_IS_SPEECH_START, False)
        return p


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _safe_is_speech(vad: webrtcvad.Vad, frame: bytes) -> bool:
    try:
        return vad.is_speech(frame, TARGET_SAMPLE_RATE)
    except Exception:
        return False
