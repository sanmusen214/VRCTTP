"""
VolcMachineTranslation — 火山引擎机器翻译模块。

接收上游传来的 MessagePacket（应含 TEXT_ORIGINAL），
调用火山引擎机器翻译 HTTP API，将翻译结果写入 TEXT_TRANSLATED 后传递给下游。

API 文档参考：
  POST https://openspeech.bytedance.com/api/v3/machine_translation/matx_translate

行为：
  - 若 TEXT_ORIGINAL 为空或包格式不对，直接透传包（不翻译）。
  - 网络错误时记录日志并透传原始包，不抛出异常。

Config 参数：
    app_id (str): 火山引擎应用 ID（X-Api-App-Key）
    access_key (str): 访问密钥（X-Api-Access-Key）
    source_language (str): 源语言（如 "en"），空字符串表示自动检测，默认 ""
    target_language (str): 目标语言（如 "zh"），必填，默认 "zh"
"""

from __future__ import annotations

import logging
import uuid

import requests

from core.packet import (
    KEY_IS_FINAL_SEGMENT,
    KEY_IS_PARTIAL,
    KEY_TEXT_ORIGINAL,
    KEY_TEXT_TRANSLATED,
    KEY_TARGET_LANG,
    MessagePacket,
)
from modules.translation.base import BasePacketConsumerModule

logger = logging.getLogger(__name__)

_TRANSLATE_URL = "https://openspeech.bytedance.com/api/v3/machine_translation/matx_translate"
_RESOURCE_ID = "volc.speech.mt"
_CODE_SUCCESS = 20000000

# 请求超时（秒）：连接超时 5s，读取超时 8s
_REQUEST_TIMEOUT = (5, 8)


class VolcMachineTranslation(BasePacketConsumerModule):
    """
    火山引擎机器翻译模块。

    在翻译链（translation_chain）中通常作为 VolcStreamingSTT 的下游：
        VolcStreamingSTT → VolcMachineTranslation → ConsumerModules
    """

    def __init__(self, module_id: str, config: dict) -> None:
        super().__init__(module_id, config)
        self._api_key: str = config.get("api_key", "")
        self._app_id: str = config.get("app_id", "")
        self._access_key: str = config.get("access_key", "")
        self._source_language: str = config.get("source_language", "")
        self._target_language: str = config.get("target_language", "zh")

        # 复用 HTTP 会话以提高性能（keep-alive）
        self._session = requests.Session()

    def on_after_stop(self) -> None:
        self._session.close()

    # ------------------------------------------------------------------
    # PacketConsumerModule 接口
    # ------------------------------------------------------------------

    def process_packet(self, packet: MessagePacket) -> list[MessagePacket]:
        """
        翻译包中的 TEXT_ORIGINAL，写入 TEXT_TRANSLATED。

        - 跳过无 TEXT_ORIGINAL 的包
        """
        text: str = packet.get(KEY_TEXT_ORIGINAL, "")

        if not text or not text.strip():
            return [packet]  # 无文本，直接透传
        # 为 partial 包的话，直接透传不翻译
        if packet.is_partial:
            return [packet]

        translated = self._translate(text.strip())

        out = packet.clone()
        out.set(KEY_TEXT_TRANSLATED, translated)
        out.set(KEY_TARGET_LANG, self._target_language)
        if translated:
            logger.info(
                "[%s] 翻译: %s → %s",
                self.module_id,
                text.strip()[:50],
                translated[:50],
            )
        return [out]

    # ------------------------------------------------------------------
    # HTTP 翻译实现
    # ------------------------------------------------------------------

    def _translate(self, text: str) -> str:
        """调用火山引擎机器翻译 API，返回翻译结果（失败返回空字符串）。"""
        if self._api_key:
            headers = {
                "X-Api-Key": self._api_key,
                "X-Api-Resource-Id": _RESOURCE_ID,
                "X-Api-Request-Id": str(uuid.uuid4()),
                "Content-Type": "application/json; charset=utf-8",
            }
        else:
            headers = {
                "X-Api-App-Key": self._app_id,
                "X-Api-Access-Key": self._access_key,
                "X-Api-Resource-Id": _RESOURCE_ID,
                "X-Api-Request-Id": str(uuid.uuid4()),
                "Content-Type": "application/json; charset=utf-8",
            }
        body = {
            "text_list": [text],
            "target_language": self._target_language,
        }
        if self._source_language:
            body["source_language"] = self._source_language

        try:
            logger.info("[%s] 发起翻译请求: %s", self.module_id, text.strip()[:80])
            resp = self._session.post(
                _TRANSLATE_URL,
                headers=headers,
                json=body,
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.error("[%s] 翻译请求失败: %s", self.module_id, e)
            return ""
        except Exception:
            logger.exception("[%s] 翻译响应解析失败", self.module_id)
            return ""

        code = data.get("code", -1)
        if code != _CODE_SUCCESS:
            msg = data.get("message", "unknown")
            logger.error("[%s] 翻译 API 返回错误 %s: %s", self.module_id, code, msg)
            return ""

        try:
            translation_list = data["data"]["translation_list"]
            return translation_list[0].get("translation", "")
        except (KeyError, IndexError):
            logger.error("[%s] 翻译响应格式异常: %s", self.module_id, data)
            return ""
