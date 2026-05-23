"""
全局 GUI 状态模块。

在 create_app(engine) 中调用 init()，之后各页面/组件通过 get_engine() 使用引擎。
output_buffer / output_lock 用于接收 TerminalConsumer 的实时翻译输出。
"""
from __future__ import annotations

import threading
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.engine import PipelineEngine

MAX_OUTPUT_LINES = 200

_engine: PipelineEngine | None = None
output_buffer: deque[dict] = deque(maxlen=MAX_OUTPUT_LINES)
output_lock = threading.Lock()


def init(engine: PipelineEngine) -> None:
    """初始化全局引擎引用，由 create_app() 调用一次。"""
    global _engine
    _engine = engine


def get_engine() -> PipelineEngine:
    """获取引擎实例，在 init() 调用前访问会抛出 RuntimeError。"""
    if _engine is None:
        raise RuntimeError("GUI state not initialized — call gui.state.init(engine) first")
    return _engine
