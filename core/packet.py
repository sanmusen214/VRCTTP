"""
MessagePacket — 在管道中流动的信息包。
每个包包含一组键值对数据，由上游模块逐步填充，向下游传递。

节点时间戳约定：
  每个处理节点（ref_id）在产生输出包时，通过 mark_node_time(ref_id) 将
  处理时刻写入 data["timestamp_{ref_id}"]（float, Unix 时间戳）。
  下游消费者可通过该字段将来自不同分叉的包聚合为同一"组"显示。
"""

from __future__ import annotations

import copy
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# 标准数据键常量
# 约定所有模块使用以下 key 名称，避免拼写错误
# ---------------------------------------------------------------------------

# 阶段一：音频源
KEY_AUDIO_DATA = "audio_data"           # bytes, 16-bit PCM mono 16kHz
KEY_SAMPLE_RATE = "sample_rate"         # int, e.g. 16000
KEY_SOURCE_TYPE = "source_type"         # str: "microphone" | "loopback"
KEY_SOURCE_NAME = "source_name"         # str: 设备名或进程名
KEY_IS_FINAL_SEGMENT = "is_final_segment"  # bool: True 表示这是一个完整语音分段

# 阶段二：翻译
KEY_TEXT_ORIGINAL = "text_original"     # str: 识别出的原文
KEY_TEXT_TRANSLATED = "text_translated" # str: 翻译后的文字
KEY_SOURCE_LANG = "source_lang"         # str: 原文语言代码, e.g. "en"
KEY_TARGET_LANG = "target_lang"         # str: 目标语言代码, e.g. "zh"
KEY_IS_PARTIAL = "is_partial"           # bool: True 表示这是流式中间结果

# 流式音频模式专用
KEY_IS_SPEECH_START = "is_speech_start"  # bool: True 表示这是新语音段的第一帧
KEY_AUDIO_CHUNK_INDEX = "audio_chunk_idx"  # int: 流式模式下的帧序号（调试用）

# 元信息
KEY_TIMESTAMP = "timestamp"             # float: 音频捕获时的 UTC 时间戳


@dataclass
class MessagePacket:
    """
    在管道中流动的信息包。

    Attributes:
        id: 包的唯一标识符（UUID4 字符串）
        pipeline_id: 所属 pipeline 的 ID
        created_at: 包的创建时间（UTC）
        data: 模块间传递的键值对数据
        is_partial: 是否为流式中间结果（partial 包通常不触发最终消费）
        _pipeline_routes: 所属 pipeline 的路由图（ref_id → [next_ref_id, ...]），
            由 PacketProducerModule 注入，clone() 时浅复制（共享引用）。
        _pipeline_modules: 所属 pipeline 的模块实例字典（ref_id → BaseModule），
            由 PacketProducerModule 注入，clone() 时浅复制（共享引用）。
    """

    pipeline_id: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    data: dict[str, Any] = field(default_factory=dict)
    # 路由上下文：由生产者注入，clone 时以引用共享（不深拷贝）
    _pipeline_routes: dict[str, list[str]] = field(default_factory=dict)
    _pipeline_modules: dict[str, Any] = field(default_factory=dict)  # ref_id → BaseModule

    def __post_init__(self) -> None:
        # 确保 is_partial 始终存在于 data 中，property 由此唯一读写
        self.data.setdefault("is_partial", False)

    @property
    def is_partial(self) -> bool:
        """是否为流式中间结果。值唯一存储于 data[\"is_partial\"]，通过 property 访问。"""
        return self.data.get("is_partial", False)

    @is_partial.setter
    def is_partial(self, value: bool) -> None:
        self.data["is_partial"] = value

    # ------------------------------------------------------------------
    # 便捷访问方法
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def __contains__(self, key: str) -> bool:
        return key in self.data

    def mark_node_time(self, ref_id: str) -> None:
        """
        将当前模块 ref_id 的处理时刻写入包。
        写入 key = "timestamp_{ref_id}"，value = float Unix 时间戳。
        同一 ref_id 产出的所有"分叉克隆包"共享相同值，
        供下游消费者按公共祖先分组合并显示。
        """
        self.data[f"timestamp_{ref_id}"] = time.time()

    # ------------------------------------------------------------------
    # 克隆（广播到多个下游时使用）
    # ------------------------------------------------------------------

    def clone(self) -> MessagePacket:
        """
        创建当前包的深度副本，使用新的 UUID。
        用于将同一包广播给多个下游模块时，各自持有独立副本。

        _pipeline_routes 和 _pipeline_modules 以引用共享（不深拷贝），
        确保同一 pipeline 内所有分叉包遵循相同路由图。
        """
        new_packet = MessagePacket(
            pipeline_id=self.pipeline_id,
            id=str(uuid.uuid4()),
            created_at=self.created_at,
            data=copy.deepcopy(self.data),
            _pipeline_routes=self._pipeline_routes,   # 共享引用，不深拷贝
            _pipeline_modules=self._pipeline_modules, # 共享引用，不深拷贝
        )
        return new_packet

    def __repr__(self) -> str:
        keys = list(self.data.keys())
        return (
            f"MessagePacket(pipeline={self.pipeline_id!r}, "
            f"id={self.id[:8]}..., partial={self.is_partial}, keys={keys})"
        )
