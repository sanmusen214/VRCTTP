"""
VolcStreamingSTT — 火山引擎双向流式语音识别模块。

使用火山引擎 bigmodel_async 接口（大并发 / 按时长计费），通过 WebSocket 实现
双向流式通信，支持两种工作模式：

【批处理模式 streaming_mode=False（默认）】
  接收包含完整语音段的 MessagePacket（is_final_segment=True），
  将 PCM 数据切成 200ms 小块，流式推送到 WebSocket，等待最终识别结果，
  将 TEXT_ORIGINAL 填充后传递给下游（翻译模块等）。

【流式模式 streaming_mode=True】
  接收来自流式音频源的小块音频包：
    - is_partial=True, is_final_segment=False → 中间音频块，推送到当前 WebSocket 会话
    - is_final_segment=True                  → 语音段结束，发送结束标记并等待最终结果
  每收到识别结果就立即通过 send_to_downstream() 发送下游。
  中间识别结果以 is_partial=True 的包形式发出，最终结果以 is_partial=False 发出。

鉴权说明（与 validate_volc_stt.py 保持一致）：
  新版控制台：config["api_key"] = "<UUID 格式 X-Api-Key>"
  旧版控制台：config["app_id"] + config["access_key"]

协议要点（修复自 validate_volc_stt.py 验证）：
  - 使用 aiohttp.ClientSession().ws_connect()（而非 websockets）
  - 每帧携带 4 字节有符号序列号（POS_SEQUENCE / NEG_WITH_SEQUENCE flags）
  - 音频帧使用 gzip 压缩
  - 最后一帧 flags=NEG_WITH_SEQUENCE，序列号取负値
  - parse_response 先检查 flags & 0x01 再读序列号字段

API 文档参考：
  wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async
  https://www.volcengine.com/docs/6561/80905
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import struct
import threading
import uuid
from typing import Optional

import aiohttp

from core.module import PacketConsumerModule
from core.packet import (
    KEY_AUDIO_CHUNK_INDEX,
    KEY_AUDIO_DATA,
    KEY_IS_FINAL_SEGMENT,
    KEY_IS_PARTIAL,
    KEY_IS_SPEECH_START,
    KEY_SAMPLE_RATE,
    KEY_TEXT_ORIGINAL,
    MessagePacket,
)
from modules.translation.base import BasePacketConsumerModule

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 二进制协议常量（与官方 sauc_websocket_demo.py 及 validate_volc_stt.py 一致）
# ---------------------------------------------------------------------------

_PROTO_VERSION = 0b0001
_HEADER_SIZE = 0b0001   # 1 × 4 = 4 bytes

# 消息类型
_MSG_FULL_CLIENT_REQUEST = 0b0001   # 完整客户端请求（JSON 配置）
_MSG_AUDIO_ONLY = 0b0010            # 仅音频数据
_MSG_FULL_SERVER_RESPONSE = 0b1001  # 完整服务端响应
_MSG_ERROR = 0b1111                 # 错误

# message_type_specific_flags
_FLAG_POS_SEQ = 0b0001       # 含正序列号字段
_FLAG_NEG_WITH_SEQ = 0b0011  # 最后包：含负序列号字段

# 序列化方式
_SER_JSON = 0b0001
_SER_NONE = 0b0000

# 压缩方式
_COMP_GZIP = 0b0001
_COMP_NONE = 0b0000

# WebSocket 端点（双向流式优化版）
_WS_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream"
_WS_URL_STREAMING = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"

# ---------------------------------------------------------------------------
# 二进制协议辅助函数
# ---------------------------------------------------------------------------

def _make_header(msg_type: int, flags: int, serialization: int, compression: int) -> bytes:
    """构建 4 字节二进制协议头。"""
    return bytes([
        (_PROTO_VERSION << 4) | _HEADER_SIZE,
        (msg_type << 4) | flags,
        (serialization << 4) | compression,
        0x00,
    ])


def _build_full_client_request(config_dict: dict, seq: int = 1) -> bytes:
    """
    构建完整客户端请求帧（JSON + gzip + 序列号）。
    格式：header(4) + seq(4, signed '>i') + payload_size(4) + gzip(JSON)
    """
    header = _make_header(_MSG_FULL_CLIENT_REQUEST, _FLAG_POS_SEQ, _SER_JSON, _COMP_GZIP)
    payload = gzip.compress(json.dumps(config_dict).encode("utf-8"))
    return header + struct.pack(">i", seq) + struct.pack(">I", len(payload)) + payload


def _build_audio_packet(audio_bytes: bytes, seq: int, is_last: bool = False) -> bytes:
    """
    构建音频数据帧（gzip 压缩 + 序列号）。
    最后一帧：flags=NEG_WITH_SEQUENCE，seq 取负値。
    格式：header(4) + seq(4, signed '>i') + payload_size(4) + gzip(PCM)
    """
    if is_last:
        flags = _FLAG_NEG_WITH_SEQ
        seq_val = -seq
    else:
        flags = _FLAG_POS_SEQ
        seq_val = seq
    header = _make_header(_MSG_AUDIO_ONLY, flags, _SER_NONE, _COMP_GZIP)
    compressed = gzip.compress(audio_bytes)
    return header + struct.pack(">i", seq_val) + struct.pack(">I", len(compressed)) + compressed


def _parse_server_response(data: bytes) -> dict:
    """
    解析服务端响应帧（与官方 demo ResponseParser 逻辑一致）。

    先检查 flags bits 决定是否读取序列号字段，再按消息类型解析 payload。
    返回 dict：{"type": "response"/"unknown", "is_last": bool, "data": ...}
    遇到错误帧 raise ValueError。
    """
    header_size = (data[0] & 0xF) * 4
    msg_type = (data[1] >> 4) & 0xF
    flags = data[1] & 0xF
    compression = data[2] & 0xF
    serialization = (data[2] >> 4) & 0xF
    payload = data[header_size:]

    seq = None
    is_last = False

    if flags & 0x01:   # 含序列号字段
        seq = struct.unpack(">i", payload[:4])[0]
        payload = payload[4:]
    if flags & 0x02:   # 最后一包
        is_last = True
    if flags & 0x04:   # 事件字段（跳过）
        payload = payload[4:]

    if msg_type == _MSG_FULL_SERVER_RESPONSE:
        payload_size = struct.unpack(">I", payload[:4])[0]
        payload = payload[4:4 + payload_size]
        if compression == _COMP_GZIP:
            payload = gzip.decompress(payload)
        result = {}
        if serialization == _SER_JSON:
            result = json.loads(payload.decode())
        return {"type": "response", "seq": seq, "is_last": is_last, "data": result}

    elif msg_type == _MSG_ERROR:
        code = struct.unpack(">i", payload[:4])[0]
        payload_size = struct.unpack(">I", payload[4:8])[0]
        payload = payload[8:8 + payload_size]
        if compression == _COMP_GZIP:
            payload = gzip.decompress(payload)
        raise ValueError(f"服务端错误 {code}: {payload.decode(errors='replace')}")

    return {"type": "unknown", "msg_type": msg_type}


# ---------------------------------------------------------------------------
# 主模块类
# ---------------------------------------------------------------------------

class VolcStreamingSTT(BasePacketConsumerModule):
    """
    火山引擎语音识别翻译模块（双向流式）。

    Config 参数：
        api_key (str): 【新版控制台】X-Api-Key（UUID 格式）
        app_id (str): 【旧版控制台】X-Api-App-Key（纯数字 App ID）
        access_key (str): 【旧版控制台】X-Api-Access-Key（Access Token）
        resource_id (str): 资源 ID，默认 "volc.seedasr.sauc.duration"（豆包2.0按小时）
        language (str): 识别语言（如 "zh-CN"、"en-US"），默认 "zh-CN"
        chunk_ms (int): 分块推送的时长（ms），默认 200
        streaming_mode (bool): 是否启用流式模式（配合流式音频源），默认 False
    """

    def __init__(self, module_id: str, config: dict) -> None:
        super().__init__(module_id, config)
        # 鉴权（新版控制台优先）
        self._api_key: str = config.get("api_key", "")
        self._app_id: str = config.get("app_id", "")
        self._access_key: str = config.get("access_key", "")
        self._resource_id: str = config.get("resource_id", "volc.seedasr.sauc.duration")
        self._language: str = config.get("language", "zh-CN")
        self._chunk_ms: int = int(config.get("chunk_ms", 200))
        self._streaming_mode: bool = bool(config.get("streaming_mode", False))

        # 流式模式状态
        self._stream_lock = threading.Lock()
        self._stream_session: Optional[_StreamSession] = None
        self._aiohttp_session: Optional[aiohttp.ClientSession] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # 生命周期钉子（流式模式需要后台 asyncio 线程）
    # ------------------------------------------------------------------

    def on_start(self) -> None:
        if self._streaming_mode:
            self._loop = asyncio.new_event_loop()
            self._loop_thread = threading.Thread(
                target=self._loop.run_forever,
                name=f"{self.module_id}-asyncio",
                daemon=True,
            )
            self._loop_thread.start()

    def on_after_stop(self) -> None:
        if self._loop and self._loop_thread:
            if self._stream_session:
                asyncio.run_coroutine_threadsafe(
                    self._stream_session.close(), self._loop
                ).result(timeout=5)
                self._stream_session = None
            if self._aiohttp_session:
                asyncio.run_coroutine_threadsafe(
                    self._aiohttp_session.close(), self._loop
                ).result(timeout=5)
                self._aiohttp_session = None
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._loop_thread.join(timeout=5)
            self._loop = None

    # ------------------------------------------------------------------
    # PacketConsumerModule 接口
    # ------------------------------------------------------------------

    def process_packet(self, packet: MessagePacket) -> list[MessagePacket]:
        """
        批处理模式：接收完整语音段，流式推送给 API，返回含识别文本的包列表。
        流式模式：由 _run() 直接管理，process_packet 在这里仅处理完整段（兜底）。
        """
        if self._streaming_mode:
            return self._process_streaming(packet)
        return self._process_batch(packet)

    # ------------------------------------------------------------------
    # 批处理模式：接收完整 PCM，WebSocket 推送后等待结果
    # ------------------------------------------------------------------

    def _process_batch(self, packet: MessagePacket) -> list[MessagePacket]:
        """一次性处理完整语音段（is_final_segment=True）。"""
        if not packet.get(KEY_IS_FINAL_SEGMENT):
            return []

        pcm: bytes = packet.get(KEY_AUDIO_DATA, b"")
        if len(pcm) < 3200:  # < 0.1s，忽略
            return []

        try:
            text = asyncio.run(self._transcribe_batch(pcm))
        except Exception:
            logger.exception("[%s] 批处理转写失败", self.module_id)
            return []

        if not text or not text.strip():
            return []

        out = packet.clone()
        out.is_partial = False
        out.set(KEY_IS_PARTIAL, False)
        out.set(KEY_IS_FINAL_SEGMENT, True)
        out.set(KEY_TEXT_ORIGINAL, text.strip())
        logger.info("[%s] 识别结果: %s", self.module_id, text.strip())
        return [out]

    async def _transcribe_batch(self, pcm: bytes) -> str:
        """连接 WebSocket，分块推送完整 PCM，并发收发，返回最终文本。"""
        headers = self._make_ws_headers()
        config_payload = self._make_config_payload()
        chunk_bytes = self._chunk_ms * 16000 * 2 // 1000
        final_text = ""

        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(_WS_URL, headers=headers) as ws:
                seq = 1

                # 1. 发送配置帧，等待服务端确认
                await ws.send_bytes(_build_full_client_request(config_payload, seq))
                seq += 1
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=8)
                    if msg.type == aiohttp.WSMsgType.BINARY:
                        logger.debug("[%s] 配置确认: %s", self.module_id,
                                     _parse_server_response(msg.data))
                except Exception as e:
                    logger.warning("[%s] 配置响应异常: %s", self.module_id, e)

                # 2. 并发：发送音频块 + 接收识别结果
                async def sender() -> None:
                    nonlocal seq
                    offset = 0
                    while offset < len(pcm):
                        end = min(offset + chunk_bytes, len(pcm))
                        chunk = pcm[offset:end]
                        is_last = (end >= len(pcm))
                        await ws.send_bytes(_build_audio_packet(chunk, seq, is_last=is_last))
                        if not is_last:
                            seq += 1
                        offset = end

                async def receiver() -> None:
                    nonlocal final_text
                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.BINARY:
                            break
                        try:
                            parsed = _parse_server_response(msg.data)
                        except ValueError as e:
                            logger.error("[%s] %s", self.module_id, e)
                            break
                        if parsed["type"] != "response":
                            break
                        text = parsed["data"].get("result", {}).get("text", "").strip()
                        if text:
                            final_text = text
                        if parsed.get("is_last"):
                            break

                await asyncio.gather(sender(), receiver())

        return final_text

    # ------------------------------------------------------------------
    # 流式模式：维护持久 WebSocket 会话
    # ------------------------------------------------------------------

    def _process_streaming(self, packet: MessagePacket) -> list[MessagePacket]:
        """
        流式模式下的包处理：提交到 asyncio 事件循环的异步处理，
        结果通过 send_to_downstream() 直接发出（不在 process_packet 返回值中）。
        """
        if self._loop is None:
            return []

        asyncio.run_coroutine_threadsafe(
            self._handle_streaming_packet(packet),
            self._loop,
        )
        return []  # 结果直接由异步侧调用 send_to_downstream

    async def _get_or_create_aiohttp_session(self) -> aiohttp.ClientSession:
        """在 streaming asyncio 循环中惰性创建 aiohttp.ClientSession。"""
        if self._aiohttp_session is None or self._aiohttp_session.closed:
            self._aiohttp_session = aiohttp.ClientSession()
        return self._aiohttp_session

    async def _handle_streaming_packet(self, packet: MessagePacket) -> None:
        """异步处理流式音频包。"""
        is_partial = packet.is_partial
        is_final = packet.get(KEY_IS_FINAL_SEGMENT, False)
        pcm: bytes = packet.get(KEY_AUDIO_DATA, b"")

        async with _AsyncLock(self._stream_lock):
            # --- 首块或中间块：推送到当前会话 ---
            if is_partial and not is_final:
                if self._stream_session is None:
                    session = await self._get_or_create_aiohttp_session()
                    self._stream_session = _StreamSession(
                        aiohttp_session=session,
                        headers=self._make_ws_headers(),
                        config=self._make_config_payload(),
                        source_packet=packet,
                        on_partial=self._emit_partial,
                        module_id=self.module_id,
                    )
                    await self._stream_session.open()

                if pcm:
                    await self._stream_session.send_audio(pcm, is_last=False)

            # --- 最终包：发送结束帧，等待完整结果 ---
            elif is_final:
                if self._stream_session is None and pcm:
                    # 仅有最终包（可能是单帧段），降级为批处理
                    text = await self._transcribe_batch(pcm)
                    if text.strip():
                        self._emit_final(packet, text.strip())
                    return

                if self._stream_session is not None:
                    if pcm:
                        await self._stream_session.send_audio(pcm, is_last=True)
                    else:
                        await self._stream_session.send_end()

                    final_text = await self._stream_session.wait_for_final()
                    await self._stream_session.close()
                    self._stream_session = None

                    if final_text.strip():
                        self._emit_final(packet, final_text.strip())

    def _emit_partial(self, source_packet: MessagePacket, text: str) -> None:
        """向下游发送中间识别结果（is_partial=True）。"""
        out = source_packet.clone()
        out.is_partial = True
        out.set(KEY_IS_PARTIAL, True)
        out.set(KEY_IS_FINAL_SEGMENT, False)
        out.set(KEY_TEXT_ORIGINAL, text)
        self.send_to_downstream(out)

    def _emit_final(self, source_packet: MessagePacket, text: str) -> None:
        """向下游发送最终识别结果（is_partial=False）。"""
        out = source_packet.clone()
        out.is_partial = False
        out.set(KEY_IS_PARTIAL, False)
        out.set(KEY_IS_FINAL_SEGMENT, True)
        out.set(KEY_TEXT_ORIGINAL, text)
        logger.info("[%s] 最终识别: %s", self.module_id, text)
        self.send_to_downstream(out)

    # ------------------------------------------------------------------
    # 协议构建辅助
    # ------------------------------------------------------------------

    def _make_ws_headers(self) -> dict[str, str]:
        """构建 WebSocket 鉴权头（新版控制台优先）。"""
        if self._api_key:
            return {
                "X-Api-Key": self._api_key,
                "X-Api-Resource-Id": self._resource_id,
                "X-Api-Request-Id": str(uuid.uuid4()),
            }
        return {
            "X-Api-App-Key": self._app_id,
            "X-Api-Access-Key": self._access_key,
            "X-Api-Resource-Id": self._resource_id,
            "X-Api-Request-Id": str(uuid.uuid4()),
        }

    def _make_config_payload(self) -> dict:
        return {
            "user": {"uid": str(uuid.uuid4())},
            "audio": {
                "format": "pcm",
                "codec": "raw",
                "rate": 16000,
                "bits": 16,
                "channel": 1,
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
                "enable_ddc": True,
                "show_utterances": True,
                "enable_nonstream": False,
                "language": self._language,
            },
        }


# ---------------------------------------------------------------------------
# 流式会话辅助类
# ---------------------------------------------------------------------------

class _StreamSession:
    """管理单段语音的 WebSocket 会话生命周期（aiohttp）。"""

    def __init__(
        self,
        aiohttp_session: aiohttp.ClientSession,
        headers: dict,
        config: dict,
        source_packet: MessagePacket,
        on_partial,
        module_id: str = "",
    ) -> None:
        self._session = aiohttp_session
        self._headers = headers
        self._config = config
        self.source_packet = source_packet
        self._on_partial = on_partial
        self._module_id = module_id
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._recv_task: Optional[asyncio.Task] = None
        self._final_text = ""
        self._final_event = asyncio.Event()
        self._seq = 1

    async def open(self) -> None:
        """建立 WebSocket 连接并发送配置请求。"""
        self._ws = await self._session.ws_connect(_WS_URL_STREAMING, headers=self._headers)
        await self._ws.send_bytes(_build_full_client_request(self._config, self._seq))
        self._seq += 1
        # 等待服务端确认
        try:
            msg = await asyncio.wait_for(self._ws.receive(), timeout=8)
            if msg.type == aiohttp.WSMsgType.BINARY:
                logger.debug("[%s] StreamSession 配置确认", self._module_id)
        except Exception as e:
            logger.warning("[%s] StreamSession 配置响应异常: %s", self._module_id, e)
        # 启动后台接收任务
        self._recv_task = asyncio.create_task(self._recv_loop())

    async def send_audio(self, pcm: bytes, is_last: bool) -> None:
        if self._ws and not self._ws.closed:
            await self._ws.send_bytes(_build_audio_packet(pcm, self._seq, is_last=is_last))
            if not is_last:
                self._seq += 1

    async def send_end(self) -> None:
        """发送空的结束标记帧。"""
        if self._ws and not self._ws.closed:
            await self._ws.send_bytes(
                _build_audio_packet(b"\x00" * 960, self._seq, is_last=True)
            )

    async def wait_for_final(self) -> str:
        """等待最终识别结果（最多 15s）。"""
        try:
            await asyncio.wait_for(self._final_event.wait(), timeout=15)
        except asyncio.TimeoutError:
            logger.warning("[%s] 等待最终识别结果超时", self._module_id)
        return self._final_text

    async def close(self) -> None:
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self._ws and not self._ws.closed:
            await self._ws.close()

    async def _recv_loop(self) -> None:
        """后台持续接收服务端响应，提取识别文本。"""
        try:
            async for msg in self._ws:
                if msg.type != aiohttp.WSMsgType.BINARY:
                    break
                try:
                    parsed = _parse_server_response(msg.data)
                except ValueError as e:
                    logger.error("[%s] StreamSession %s", self._module_id, e)
                    self._final_event.set()
                    break

                if parsed["type"] != "response":
                    break

                text = parsed["data"].get("result", {}).get("text", "").strip()
                if text:
                    self._final_text = text
                    self._on_partial(self.source_packet, text)

                # is_last via flags（主要检测方式）
                if parsed.get("is_last"):
                    self._final_event.set()
                    break

                # fallback：definite utterance（bigmodel_async 可能不发 is_last）
                utterances = parsed["data"].get("result", {}).get("utterances", [])
                if utterances and utterances[-1].get("definite"):
                    self._final_event.set()

        except aiohttp.ClientConnectionError:
            self._final_event.set()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[%s] StreamSession 接收循环出错", self._module_id)
            self._final_event.set()


class _AsyncLock:
    """将 threading.Lock 包装为 async context manager（不阻塞事件循环）。"""

    def __init__(self, lock: threading.Lock) -> None:
        self._lock = lock

    async def __aenter__(self):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._lock.acquire)
        return self

    async def __aexit__(self, *args):
        self._lock.release()
