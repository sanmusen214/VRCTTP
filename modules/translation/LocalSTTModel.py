"""
LocalParaformerSTT — 基于 FunASR 本地 Paraformer 流式语音识别模块。

支持两种工作模式（`streaming_mode`）：

模式一：streaming_mode=False（批处理，默认）
  - 仅接受 is_final_segment=True 的完整语音段包
  - 整段音频一次性送入模型推理
  - 返回单个 is_partial=False 的最终识别包

模式二：streaming_mode=True（流式）
  - 接收音频源以流式 chunk（is_partial=True）发出的小块
  - 内部维护 float32 音频缓冲区；每积累够一个模型推理窗口（chunk_stride 样本）
    就调用 model.generate(is_final=False)，通过 send_to_downstream 发出 partial 包
  - 语音段结束帧（is_final_segment=True）时，以 is_final=True 调用模型输出最终文字，
    通过 process_packet 返回列表将 final 包发出
  - 收到 is_speech_start=True 标志时自动重置 cache 和 buffer（新语音段开始）

【重要】文字拼接说明：
  流式模式：本地 FunASR 模型每次 generate() 仅返回当前 chunk 新增识别的词语（增量），
  而非已识别文字的完整累积（与云端 API 行为不同）。
  因此流式模块内部维护 _accumulated_text，每个 chunk 的识别结果追加拼接：
    - partial 包的 KEY_TEXT_ORIGINAL = 迄今为止完整累积文字（供实时预览）
    - final   包的 KEY_TEXT_ORIGINAL = 整句完整累积文字（可衔接翻译模块）
  批处理模式（_infer_full）采用真正的批量推理：整段音频直接传入 generate()，
  无需分块累积，离线模型一次调用返回完整文字（若含内置 VAD 可能返回多段，拼接后输出）。

输出包字段与 VolcStreamingSTT 完全一致：
  - KEY_TEXT_ORIGINAL  识别出的文字
  - KEY_IS_PARTIAL     True=中间结果 / False=最终结果
  - KEY_IS_FINAL_SEGMENT True=语音段已结束

Config 参数：
  model_path (str, 必填): 本地模型目录路径，如
      "C:\\path\\to\\speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online"
  model_name (str): 传给 AutoModel 的 model 字段。
      批处理模式推荐离线模型（如 "paraformer-zh"）；默认 "paraformer-zh-streaming" 仅用于流式模式。
  streaming_mode (bool): 是否开启流式推理，默认 False（批处理）
  chunk_size (list): 仅流式模式使用，FunASR chunk_size 参数，默认 [0, 10, 5]（每次推理 600ms 窗口）
  encoder_chunk_look_back (int): 仅流式模式使用，默认 4
  decoder_chunk_look_back (int): 仅流式模式使用，默认 1
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from core.module import PacketConsumerModule
from core.packet import (
    KEY_AUDIO_DATA,
    KEY_IS_FINAL_SEGMENT,
    KEY_IS_PARTIAL,
    KEY_IS_SPEECH_START,
    KEY_TEXT_ORIGINAL,
    MessagePacket,
)
from modules.translation.base import BasePacketConsumerModule
from core.module import ParamType
from funasr.utils.postprocess_utils import rich_transcription_postprocess

logger = logging.getLogger(__name__)


@dataclass
class _StreamState:
    """单条 pipeline 的流式识别运行时状态（每个语音段重置）。"""
    cache: dict = field(default_factory=dict)
    audio_buffer: np.ndarray = field(default_factory=lambda: np.array([], dtype=np.float32))
    segment_source_packet: Optional[Any] = None
    accumulated_text: str = ""


class LocalParaformerSTT(BasePacketConsumerModule):
    """本地 FunASR Paraformer 流式语音识别模块。"""

    @classmethod
    def require_attributes_in_packages(cls) -> list[dict]:
        return [
            {"name": "audio_data",       "must_have": True,  "description": "16-bit PCM mono 音频字节"},
            {"name": "is_final_segment", "must_have": True,  "description": "True 表示语音段已结束"},
            {"name": "is_partial",       "must_have": False, "description": "流式模式 True=中间块"},
            {"name": "is_speech_start",  "must_have": False, "description": "True 触发缓冲区 & cache 重置"},
        ]

    @classmethod
    def add_attributes_in_packages(cls) -> list[dict]:
        return [
            {"name": "text_original",    "must_have": True,  "description": "识别出的累积原文"},
            {"name": "is_partial",       "must_have": True,  "description": "True=中间结果 / False=最终结果"},
            {"name": "is_final_segment", "must_have": True,  "description": "True=语音段已结束"},
        ]

    @classmethod
    def get_config_attributes(cls) -> list[dict]:
        return [
            {"name": "model_path",               "type": ParamType.DirPath, "default": "",                      "required": True,  "description": "本地模型目录绝对路径", "selectable": None},
            {"name": "model_name",               "type": ParamType.String,  "default": "paraformer-zh-streaming", "required": False, "description": "传给 AutoModel 的 model 字段", "selectable": None},
            {"name": "streaming_mode",           "type": ParamType.Bool,    "default": False,                    "required": False, "description": "True=流式推理（配合流式音频源），False=批处理", "selectable": None},
            {"name": "chunk_size",               "type": ParamType.List,    "default": [0, 10, 5],               "required": False, "description": "FunASR chunk_size 参数（[left, cur, right]）", "selectable": None},
            {"name": "encoder_chunk_look_back",  "type": ParamType.Int,     "default": 4,                        "required": False, "description": "编码器回看块数", "selectable": None, "min": 0, "max": 32},
            {"name": "decoder_chunk_look_back",  "type": ParamType.Int,     "default": 1,                        "required": False, "description": "解码器回看块数", "selectable": None, "min": 0, "max": 32},
        ]

    def __init__(self, module_id: str, config: dict) -> None:
        super().__init__(module_id, config)
        self._model_path: str = config.get("model_path", "")
        self._model_name: str = config.get("model_name", "paraformer-zh-streaming")
        self._streaming_mode: bool = bool(config.get("streaming_mode", False))
        self._chunk_size: list = config.get("chunk_size", [0, 10, 5])
        self._encoder_chunk_look_back: int = int(config.get("encoder_chunk_look_back", 4))
        self._decoder_chunk_look_back: int = int(config.get("decoder_chunk_look_back", 1))

        # chunk_stride = chunk_size[1] * 960，与 sensevoice_model.py 一致
        self._chunk_stride: int = self._chunk_size[1] * 960

        self._model: Optional[Any] = None
        self._model_lock = threading.Lock()

        # 流式模式运行时状态（每条 pipeline 独立，key = pipeline_id）
        # 当多条 pipeline 共用同一实例时，各自的语音段状态互不干扰
        self._stream_states: dict[str, _StreamState] = {}

    # ── 生命周期钩子 ────────────────────────────────────────────────────────

    def on_start(self) -> None:
        """线程启动前加载 FunASR 模型（耗时操作，仅执行一次）。"""
        try:
            from funasr import AutoModel  # 懒加载，避免影响不使用此模块的 pipeline
        except ImportError as e:
            raise RuntimeError(
                f"[{self.module_id}] 找不到 funasr 依赖，"
                "请运行 `pip install funasr` 后重试。"
            ) from e

        if not self._model_path:
            raise ValueError(f"[{self.module_id}] 必须在 config 中指定 model_path")

        logger.info("[%s] 正在加载本地模型: %s", self.module_id, self._model_path)
        try:
            self._model = AutoModel(
                model=self._model_name,
                model_path=self._model_path,
                disable_update=True,
                device="cpu"
            )
        except Exception as e:
            raise RuntimeError(
                f"[{self.module_id}] 加载本地 FunASR 模型失败: {e}"
            ) from e
        logger.info("[%s] 本地模型加载完成", self.module_id)

    def on_after_stop(self) -> None:
        """停止后清理运行时状态。"""
        self._stream_states.clear()

    # ── 核心处理 ─────────────────────────────────────────────────────────────

    def process_packet(self, packet: MessagePacket) -> list[MessagePacket]:
        if self._model is None:
            return []
        if self._streaming_mode:
            return self._process_streaming(packet)
        return self._process_batch(packet)

    # ── 批处理模式 ───────────────────────────────────────────────────────────

    def _process_batch(self, packet: MessagePacket) -> list[MessagePacket]:
        """仅处理完整语音段（is_final_segment=True），整段一次推理。"""
        if not packet.get(KEY_IS_FINAL_SEGMENT):
            return []

        pcm = packet.get(KEY_AUDIO_DATA, b"")
        if len(pcm) < 3200:  # 过短（< 100ms @16kHz 16bit），跳过
            return []

        audio = self._pcm_to_float32(pcm)
        text = self._infer_full(audio)
        # 把单独的 . 替换成空
        text = text.replace(".", "")
        if not text or not text.strip():
            return []

        out = packet.clone()
        out.is_partial = False
        out.set(KEY_IS_PARTIAL, False)
        out.set(KEY_IS_FINAL_SEGMENT, True)
        out.set(KEY_TEXT_ORIGINAL, text.strip())
        logger.info("[%s] 批处理识别结果: %s", self.module_id, text.strip())
        return [out]

    def _infer_full(self, audio: np.ndarray) -> str:
        """
        将完整音频数组一次性送入模型推理（批处理模式）。

        参照 sensevoice_model_batch.py 的批量推理方式：整段 float32 数组直接作为
        input 传给 model.generate()，不分块、不传流式状态参数
        （cache / is_final / chunk_size / encoder_chunk_look_back 等），
        由 FunASR 内部完成分帧与解码，一次调用返回完整文字。

        离线模型（如 paraformer-zh）若内置了 VAD，generate() 可能返回多个分段结果，
        此处将所有分段文字拼接后作为整句返回。
        """
        with self._model_lock:
            try:
                # sensevoice: <|en|><|EMO_UNKNOWN|><|Speech|><|withitn|>
                res = self._model.generate(
                    input=audio,
                    language="auto",
                    use_itn=True,
                    batch_size_s=60,
                )
                text_result = rich_transcription_postprocess(res[0]["text"]) if res else ""
            except Exception:
                logger.exception("[%s] 批处理推理失败", self.module_id)
                return ""
        if not text_result:
            return ""
        # 离线模型可能因内置 VAD 将长音频拆分为多段，逐段拼接为完整句子
        return text_result

    # ── 流式模式 ─────────────────────────────────────────────────────────────

    def _process_streaming(self, packet: MessagePacket) -> list[MessagePacket]:
        """
        流式模式处理逻辑：
        - is_speech_start=True → 重置 cache/buffer，记录源包
        - is_partial=True, is_final_segment=False → 追加到 buffer；
          buffer 够一帧则推理，emit partial via send_to_downstream
        - is_final_segment=True → 推理剩余 buffer（is_final=True），
          返回 final 包列表

        各 pipeline 的状态通过 pipeline_id 隔离，共用实例时互不干扰。
        """
        pipeline_id = packet.pipeline_id
        state = self._get_stream_state(pipeline_id)

        is_speech_start = packet.get(KEY_IS_SPEECH_START, False)
        is_partial = packet.is_partial
        is_final = packet.get(KEY_IS_FINAL_SEGMENT, False)
        pcm = packet.get(KEY_AUDIO_DATA, b"")

        # 新语音段开始，重置该 pipeline 的状态
        if is_speech_start:
            self._reset_stream_state(pipeline_id, packet)
            state = self._get_stream_state(pipeline_id)

        # 记录最新源包（用于 clone）
        if state.segment_source_packet is None:
            state.segment_source_packet = packet

        # 追加音频数据到缓冲区
        if pcm:
            chunk_f32 = self._pcm_to_float32(pcm)
            state.audio_buffer = np.concatenate([state.audio_buffer, chunk_f32])

        # 中间帧：按模型窗口大小推理，拼接增量文字后 emit partial
        if is_partial and not is_final:
            while len(state.audio_buffer) >= self._chunk_stride:
                window = state.audio_buffer[: self._chunk_stride]
                state.audio_buffer = state.audio_buffer[self._chunk_stride:]
                new_text = self._infer_chunk(state, window, is_final_chunk=False)
                if new_text and new_text.strip():
                    state.accumulated_text += new_text.strip()
                    self._emit_partial(packet, state.accumulated_text)
            return []

        # 最终帧：推理剩余 buffer（is_final=True），拼接后发出完整 final 包
        if is_final:
            remaining = state.audio_buffer
            state.audio_buffer = np.array([], dtype=np.float32)
            new_text = self._infer_chunk(
                state,
                remaining if len(remaining) > 0 else np.zeros(960, dtype=np.float32),
                is_final_chunk=True,
            )
            if new_text and new_text.strip():
                state.accumulated_text += new_text.strip()
            final_text = state.accumulated_text
            # 把单独的 . 替换成空
            final_text = final_text.replace(".", "")

            src = state.segment_source_packet or packet
            self._reset_stream_state(pipeline_id, None)

            if not final_text:
                return []

            out = src.clone()
            out.is_partial = False
            out.set(KEY_IS_PARTIAL, False)
            out.set(KEY_IS_FINAL_SEGMENT, True)
            out.set(KEY_TEXT_ORIGINAL, final_text)
            logger.info("[%s] 流式最终识别 pipeline=%s: %s", self.module_id, pipeline_id, final_text)
            return [out]

        return []

    def _infer_chunk(self, state: _StreamState, audio: np.ndarray, is_final_chunk: bool) -> str:
        """推理单个 chunk，更新 state.cache，返回识别文字。"""
        with self._model_lock:
            try:
                res = self._model.generate(
                    input=audio,
                    cache=state.cache,
                    is_final=is_final_chunk,
                    chunk_size=self._chunk_size,
                    encoder_chunk_look_back=self._encoder_chunk_look_back,
                    decoder_chunk_look_back=self._decoder_chunk_look_back,
                )
            except Exception:
                logger.exception("[%s] 流式推理失败", self.module_id)
                return ""
        return self._extract_text(res)

    def _emit_partial(self, source_packet: MessagePacket, text: str) -> None:
        """构造并发送 partial 结果包到下游。"""
        out = source_packet.clone()
        out.is_partial = True
        out.set(KEY_IS_PARTIAL, True)
        out.set(KEY_IS_FINAL_SEGMENT, False)
        out.set(KEY_TEXT_ORIGINAL, text)
        self.send_to_downstream(out)

    # ── 工具方法 ─────────────────────────────────────────────────────────────

    def _get_stream_state(self, pipeline_id: str) -> _StreamState:
        """获取指定 pipeline 的流式状态，不存在则创建。"""
        if pipeline_id not in self._stream_states:
            self._stream_states[pipeline_id] = _StreamState()
        return self._stream_states[pipeline_id]

    def _reset_stream_state(self, pipeline_id: str, source_packet: Optional[MessagePacket]) -> None:
        """重置指定 pipeline 的流式状态（每段语音开始时调用）。"""
        self._stream_states[pipeline_id] = _StreamState(
            segment_source_packet=source_packet,
        )

    @staticmethod
    def _pcm_to_float32(pcm: bytes) -> np.ndarray:
        """将 16-bit PCM bytes 转换为 float32 numpy 数组（归一化到 [-1, 1]）。"""
        return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0

    @staticmethod
    def _extract_text(res: list) -> str:
        """从 model.generate 返回列表中提取识别文字。"""
        if not res:
            return ""
        return res[0].get("text", "") if isinstance(res[0], dict) else ""
