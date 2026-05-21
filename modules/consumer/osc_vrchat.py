"""
VRChatOSCConsumer — 通过 OSC 协议将翻译结果发送到 VRChat 聊天框。

VRChat Chatbox OSC 规格：
    地址: /chatbox/input
    参数: (str text, bool send_immediately, bool trigger_sfx)
    字符上限: 144 字符（超出截断）
    换行: 使用 \\n（LF），CRLF 会产生空行需规范化

Config 参数：
    host (str): OSC 目标地址，默认 127.0.0.1
    port (int): OSC 目标端口，默认 9000
    trigger_sfx (bool): 是否触发通知音效，默认 False
    template (str): 文字模板，可用 {original} 和 {translated}
                    默认: "{translated}"
    max_chars (int): 最大字符数，默认 144
    pipeline_name (str): 由 engine 注入
    pipeline_id (str): 由 engine 注入
"""

from __future__ import annotations

import logging
import time
import threading

from pythonosc.udp_client import SimpleUDPClient

from core.module import PacketConsumerModule
from core.packet import (
    KEY_IS_PARTIAL,
    KEY_TEXT_ORIGINAL,
    KEY_TEXT_TRANSLATED,
    KEY_TARGET_LANG,
    MessagePacket,
)

logger = logging.getLogger(__name__)

VRCHAT_CHATBOX_MAX_CHARS = 144
CHATBOX_ADDRESS = "/chatbox/input"


    

class VRChatOSCConsumer(PacketConsumerModule):
    """将翻译结果发送到 VRChat 聊天框（OSC 协议）。"""

    def __init__(self, module_id: str, config: dict) -> None:
        super().__init__(module_id, config)
        self._host: str = config.get("host", "127.0.0.1")
        self._port: int = int(config.get("port", 9000))
        self._trigger_sfx: bool = config.get("trigger_sfx", False)
        self._max_chars: int = int(config.get("max_chars", VRCHAT_CHATBOX_MAX_CHARS))
        self._client: SimpleUDPClient | None = None
        self._group_by: str = config.get("group_by", "")
        self._group_numbers: int = int(config.get("group_numbers", 1))
        self.last_10_any_packages: list[MessagePacket] = []  # 记录之前的十个包（不论是否含翻译结果）
        self.last_10_translated_packages: list[MessagePacket] = []  # 记录之前的十个包(含翻译结果)
        self._last_update_text_content = None # 记录上次更新窗口内容的文本，避免重复发送相同内容
        self.waiting_important_sent = False # 是否正在等待重要包的发送（重要包发送后会有0.4秒的冷却时间，避免短时间内重复发送）

    def _get_client(self) -> SimpleUDPClient:
        if self._client is None:
            self._client = SimpleUDPClient(self._host, self._port)
            logger.info("[%s] OSC 客户端已连接: %s:%d", self.module_id, self._host, self._port)
        return self._client
    
    def update_packages_window_content(self, packet: MessagePacket) -> None:
        """更新窗口内容，记录最近的十个包。"""
        self.last_10_any_packages.append(packet)
        if len(self.last_10_any_packages) > 10:
            self.last_10_any_packages.pop(0)
    
    def update_final_package_window_content(self, packet: MessagePacket) -> None:
        """更新窗口内容，记录最近的十个含有翻译关键字段的包。"""
        if packet.get(KEY_TEXT_TRANSLATED) and packet.get(KEY_TARGET_LANG):
            self.last_10_translated_packages.append(packet)
            if len(self.last_10_translated_packages) > 10:
                self.last_10_translated_packages.pop(0)

    def concat_final_text(self, original, translated) -> str:
        text = ""
        if original:
            text = original
        if translated:
            text = (text + f"\n{translated}") if text else "{translated}"
        return text
    
    
    def osc_send_text(self, text, close_waiting_important_status = False):
        """
        osc消息发送函数，单独抽离出来以便在需要时调用（如重要包发送时）。
        """
        client = self._get_client()
        # VRChat OSC /chatbox/input: (text, send_immediately, trigger_sfx)
        client.send_message(CHATBOX_ADDRESS, [text, True, self._trigger_sfx])
        if close_waiting_important_status:
            self.waiting_important_sent = False
        logger.debug("[%s] OSC 发送: %r", self.module_id, text[:60])

    def process_packet(self, packet: MessagePacket) -> list[MessagePacket]:
        """处理包，发送 OSC 消息。"""
        self.update_packages_window_content(packet)  # 更新窗口内容
        self.update_final_package_window_content(packet)  # 更新窗口内容
        # 多分支聚合多语言结果后发送
        original = self.last_10_any_packages[-1].get(KEY_TEXT_ORIGINAL, "") if self.last_10_any_packages else ""
        # 1. 得到最新的包含翻译的包
        latest_trans_timestamp = None
        for p in reversed(self.last_10_translated_packages):
            if p.get(self._group_by) is not None:
                p_time = p.get(self._group_by)
                if latest_trans_timestamp is None or p_time > latest_trans_timestamp:
                    latest_trans_timestamp = p_time
        # 筛选出时间戳为 latest_trans_timestamp 的翻译包
        latest_trans_packets = []
        for p in reversed(self.last_10_translated_packages):
            if p.get(KEY_TARGET_LANG) and p.get(KEY_TEXT_TRANSLATED) and p.get(self._group_by) == latest_trans_timestamp:
                latest_trans_packets.append(p)
        # 2. 字典存放不同语言的翻译结果
        trans_results = {}
        for p in latest_trans_packets:
            lang = p.get(KEY_TARGET_LANG)
            trans = p.get(KEY_TEXT_TRANSLATED)
            if lang and trans:
                trans_results[lang] = trans
        # 3. 得到历史翻译包中一共有几种语言
        # 收集历史翻译包中一共有几种语言
        existing_langs = set()
        for p in self.last_10_translated_packages:
            if p.get(KEY_TARGET_LANG) and p.get(KEY_TEXT_TRANSLATED):
                existing_langs.add(p.get(KEY_TARGET_LANG))
        sorted_existing_langs = sorted(list(existing_langs))
        # 4. 按语言顺序拼接翻译结果
        translated = ""
        count = 0
        for lang in sorted_existing_langs:
            if lang in trans_results:
                translated = (translated + f"\n{trans_results[lang]}") if translated else trans_results[lang]
                count += 1
        if self._group_numbers and count != self._group_numbers:
            # 如果设置了 group_numbers，但实际翻译结果数量不匹配，说明可能是部分翻译结果迟到了，暂不发送翻译结果（翻译结果停留在上一句译文）
            logger.debug(
                "[%s] 当前翻译结果数量 %d 不满足 group_numbers %d，暂不发送",
                self.module_id, count, self._group_numbers
            )
            return [packet]
        # 5. 当前包重要性（是否要延迟发送）
        # TODO: 区分当前包的translate结果是不是上一句话完整的翻译结果，而不是这一句的；如果是这样，不能算important包
        now_packet_is_important = False
        if not packet.is_partial and translated:
            # 如果当前包不是流式中间包，且translated不为空，说明当前包集齐了完整的翻译结果
            now_packet_is_important = True

        if not translated and not original:
            # 透传无内容的包，避免发送空消息
            return [packet]

        text = self.concat_final_text(original, translated)

        # 规范化换行并截断
        text = _normalize_newlines(text)
        text = _truncate(text, self._max_chars)

        try:
            if text == self._last_update_text_content:
                logger.debug("[%s] OSC 消息与上次相同，跳过发送: %r", self.module_id, text[:60])
                return [packet]
            if self.waiting_important_sent and not now_packet_is_important:
                # 如果当前处于等待重要包发送状态，且当前包不重要，跳过
                return [packet]
            # 如果包是重要包，延迟0.6秒发送，并设置waiting_important_sent
            if now_packet_is_important:
                self.waiting_important_sent = True
                # 在子线程后取消waiting_important_sent状态，避免阻塞主线程
                threading.Timer(0.6, self.osc_send_text, args=[text, True]).start()
            else:
                # 发送 OSC 消息
                self.osc_send_text(text)
        except Exception:
            logger.exception("[%s] OSC 发送失败", self.module_id)
            self._client = None  # 下次重新创建客户端

        return [packet]



def _normalize_newlines(text: str) -> str:
    """将 CRLF 规范化为 LF，避免 VRChat 聊天框出现多余空行。"""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _truncate(text: str, max_chars: int) -> str:
    """截断文本至指定字符数。"""
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 1] + "…"
