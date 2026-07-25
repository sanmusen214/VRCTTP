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
    from update import VersionInfo

MAX_OUTPUT_LINES = 200

_engine: PipelineEngine | None = None
output_buffer: deque[dict] = deque(maxlen=MAX_OUTPUT_LINES)
output_lock = threading.Lock()

# Pipeline 后台初始化状态（由 main.py 维护）
_engine_init_status: str = "initializing"   # "initializing" | "ready" | "error"
_engine_init_error: str = ""
_engine_init_lock = threading.Lock()

# 后台更新检测结果（None 表示尚未完成或检测失败）
_update_info: VersionInfo | None = None
_update_lock = threading.Lock()

# GUI 请求整个应用退出时设置，由 main.py 的主循环负责执行清理。
_application_shutdown_requested = threading.Event()

# 每次程序运行只允许触发一次“最低环境变量为空”的首页引导。
_initial_env_redirect_consumed = False
_initial_env_redirect_lock = threading.Lock()


def init(engine: PipelineEngine) -> None:
    """初始化全局引擎引用，由 create_app() 调用一次。"""
    global _engine
    _engine = engine
    _application_shutdown_requested.clear()


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


def set_update_info(info: VersionInfo) -> None:
    global _update_info
    with _update_lock:
        _update_info = info


def get_update_info() -> VersionInfo | None:
    with _update_lock:
        return _update_info


def request_application_shutdown() -> None:
    """请求主线程安全关闭整个应用。"""
    _application_shutdown_requested.set()


def is_application_shutdown_requested() -> bool:
    return _application_shutdown_requested.is_set()


def consume_initial_env_redirect() -> bool:
    """首次调用返回 True，之后返回 False；用于一次性启动跳转。"""
    global _initial_env_redirect_consumed
    with _initial_env_redirect_lock:
        if _initial_env_redirect_consumed:
            return False
        _initial_env_redirect_consumed = True
        return True
