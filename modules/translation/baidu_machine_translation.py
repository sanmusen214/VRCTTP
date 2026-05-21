"""
BaiduMachineTranslation — 百度通用翻译模块。

接收上游传来的 MessagePacket（应含 TEXT_ORIGINAL），
调用百度翻译开放平台 HTTP API，将翻译结果写入 TEXT_TRANSLATED 后传递给下游。

API 文档参考：
  POST https://api.fanyi.baidu.com/api/trans/vip/translate

行为：
  - 若 TEXT_ORIGINAL 为空或包格式不对，直接透传包（不翻译）。
  - is_partial=True 的包直接透传，不调用 API（减少无效请求）。
  - 网络错误时记录日志并透传原始包，不抛出异常。

Config 参数：
    app_id (str): 百度翻译开放平台 APP ID，支持 ${ENV_VAR} 替换
    app_key (str): 百度翻译开放平台 APP Key（用于签名），支持 ${ENV_VAR} 替换
    source_language (str): 源语言代码（如 "en"），默认 "auto"（自动检测）
    target_language (str): 目标语言代码（如 "zh"），必填，默认 "zh"

语言代码参考：
    自动检测: "auto" | 中文简体: "zh" | 英语: "en" | 日语: "jp"
    韩语: "kor"  | 法语: "fra" | 德语: "de" | 西班牙语: "spa"
    详见 https://api.fanyi.baidu.com/doc/21
"""

from __future__ import annotations

import hashlib
import logging
import random

import requests

from core.packet import (
    KEY_TARGET_LANG,
    KEY_TEXT_ORIGINAL,
    KEY_TEXT_TRANSLATED,
    MessagePacket,
)
from modules.translation.base import BasePacketConsumerModule

logger = logging.getLogger(__name__)

_TRANSLATE_URL = "https://api.fanyi.baidu.com/api/trans/vip/translate"

# 请求超时（秒）：连接超时 5s，读取超时 8s
_REQUEST_TIMEOUT = (5, 8)


def _make_sign(app_id: str, query: str, salt: int, app_key: str) -> str:
    """生成百度翻译 API 请求签名（MD5(appid + q + salt + appkey)）。"""
    raw = app_id + query + str(salt) + app_key
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


class BaiduMachineTranslation(BasePacketConsumerModule):
    """
    百度通用翻译模块。

    在翻译链中通常作为 STT 模块的下游：
        VolcStreamingSTT → BaiduMachineTranslation → ConsumerModules
    """

    def __init__(self, module_id: str, config: dict) -> None:
        super().__init__(module_id, config)
        self._app_id: str = config.get("app_id", "")
        self._app_key: str = config.get("app_key", "")
        self._source_language: str = config.get("source_language", "auto")
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
        - 跳过 is_partial=True 的包（流式中间结果）
        """
        text: str = packet.get(KEY_TEXT_ORIGINAL, "")

        if not text or not text.strip():
            return [packet]  # 无文本，直接透传

        if packet.is_partial:
            return [packet]  # partial 包不调用 API，直接透传

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
        """调用百度翻译 API，返回翻译结果（失败返回空字符串）。"""
        salt = random.randint(32768, 65536)
        sign = _make_sign(self._app_id, text, salt, self._app_key)

        payload = {
            "appid": self._app_id,
            "q": text,
            "from": self._source_language,
            "to": self._target_language,
            "salt": salt,
            "sign": sign,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        try:
            logger.info("[%s] 发起翻译请求: %s", self.module_id, text[:80])
            resp = self._session.post(
                _TRANSLATE_URL,
                params=payload,
                headers=headers,
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

        if "error_code" in data:
            logger.error(
                "[%s] 翻译 API 返回错误 %s: %s",
                self.module_id,
                data.get("error_code"),
                data.get("error_msg", "unknown"),
            )
            return ""

        try:
            return data["trans_result"][0]["dst"]
        except (KeyError, IndexError):
            logger.error("[%s] 翻译响应格式异常: %s", self.module_id, data)
            return ""
