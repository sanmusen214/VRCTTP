"""
PacketFilter — 通用包过滤器模块。

根据包 data 中某个字段的值决定是否放行该包，将"过滤"这一横切关注点
从业务模块（如 VolcMachineTranslation）中抽离，用显式的管道节点表达。

典型用途：
    在 config.json 的 routes 中插入 filter 节点，替代业务模块内部的条件判断。
    示例 — 只放行非中间结果（is_partial=False）的包：
        {
            "type": "filter",
            "params": {
                "field": "is_partial",
                "pass_when": false
            }
        }

Config 参数：
    field (str):       要检查的字段名。对 "is_partial" 使用 packet.is_partial 属性；
                       其他字段使用 packet.get(field) 读取。
    pass_when (Any):   字段值等于此值时放行包，否则丢弃。
    invert (bool):     若为 True，则反转判断逻辑（等于 pass_when 时丢弃）。
                       默认 False。
"""

from __future__ import annotations

import logging

from core.module import PacketConsumerModule, ParamType
from core.packet import MessagePacket

logger = logging.getLogger(__name__)

# 直接通过 .is_partial 属性访问的特殊字段
_PROPERTY_FIELDS = {"is_partial"}


class PacketFilter(PacketConsumerModule):
    """
    通用包过滤器。

    根据包中指定字段的值决定是否放行（pass through）该包。
    通过 pre_process 钩子实现：返回 None 即可在 process_packet 调用前丢弃包。
    """

    @classmethod
    def require_attributes_in_packages(cls) -> list[dict]:
        return [
            {"name": "(由 field 参数决定)", "must_have": True, "description": "field 配置项指定的包字段"},
        ]

    @classmethod
    def add_attributes_in_packages(cls) -> list[dict]:
        return []

    @classmethod
    def get_config_attributes(cls) -> list[dict]:
        return [
            {"name": "field",     "type": ParamType.String, "default": "is_partial", "required": True,  "description": "要检查的包字段名（如 \"is_partial\"）", "selectable": None},
            {"name": "pass_when", "type": ParamType.Bool,   "default": False,        "required": False, "description": "字段值等于此值时放行包", "selectable": None},
            {"name": "invert",    "type": ParamType.Bool,   "default": False,        "required": False, "description": "True 表示反转判断逻辑", "selectable": None},
        ]

    def __init__(self, module_id: str, config: dict) -> None:
        super().__init__(module_id, config)
        self._field: str = config.get("field", "is_partial")
        self._pass_when = config.get("pass_when", False)
        self._invert: bool = bool(config.get("invert", False))
        logger.debug(
            "[%s] PacketFilter 初始化: field=%r pass_when=%r invert=%r",
            self.module_id, self._field, self._pass_when, self._invert,
        )

    def pre_process(self, packet: MessagePacket) -> MessagePacket | None:
        """
        检查字段值：匹配则放行（返回包），不匹配则丢弃（返回 None）。
        """
        if self._field in _PROPERTY_FIELDS:
            value = getattr(packet, self._field)
        else:
            value = packet.get(self._field)

        match = (value == self._pass_when)
        if self._invert:
            match = not match

        if match:
            return packet
        return None

    def process_packet(self, packet: MessagePacket) -> list[MessagePacket]:
        """过滤器直接透传已通过 pre_process 检查的包。"""
        return [packet]
