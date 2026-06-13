"""
全局 GUI 状态模块。

在 create_app(engine) 中调用 init()，之后各页面/组件通过 get_engine() 使用引擎。
output_buffer / output_lock 用于接收 TerminalConsumer 的实时翻译输出。
engine_init_status 反映后台 Pipeline 初始化进度（"initializing" | "ready" | "error"），
供首页显示加载进度横幅。
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

# Pipeline 后台初始化状态（由 main.py 维护）
_engine_init_status: str = "initializing"   # "initializing" | "ready" | "error"
_engine_init_error: str = ""
_engine_init_lock = threading.Lock()


def init(engine: PipelineEngine) -> None:
    """初始化全局引擎引用，由 create_app() 调用一次。"""
    global _engine
    _engine = engine


def get_engine() -> PipelineEngine:
    """获取引擎实例，在 init() 调用前访问会抛出 RuntimeError。"""
    if _engine is None:
        raise RuntimeError("GUI state not initialized — call gui.state.init(engine) first")
    return _engine


def set_engine_ready() -> None:
    """标记 Pipeline 初始化已完成，由后台初始化线程调用。"""
    global _engine_init_status
    with _engine_init_lock:
        _engine_init_status = "ready"


def set_engine_error(msg: str) -> None:
    """标记 Pipeline 初始化失败，由后台初始化线程调用。"""
    global _engine_init_status, _engine_init_error
    with _engine_init_lock:
        _engine_init_status = "error"
        _engine_init_error = msg


def get_engine_init_status() -> tuple[str, str]:
    """返回 (status, error_msg)，status 为 'initializing' | 'ready' | 'error'。"""
    with _engine_init_lock:
        return _engine_init_status, _engine_init_error
