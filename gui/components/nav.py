"""
共享导航栏组件，包含深色/浅色主题实时切换。

直接读取及修改 config.json 中的 gui.dark_mode 并持久化。
"""
from __future__ import annotations

from nicegui import app, ui
from gui.state import get_engine

_PAGES = [
    ("首页",     "/"),
    ("文字输入与输出", "/output"),
    ("管道管理", "/pipelines"),
    ("模块目录", "/modules"),
    ("配置编辑", "/config"),
    ("环境变量", "/env"),
]


def create_nav(title: str = "VRCTTP 实时翻译 群号 964670098") -> None:
    """在当前页面顶部渲染导航栏（含深色/浅色切换开关）。"""
    dark = ui.dark_mode()
    engine = get_engine()
    raw = engine.get_raw_config()
    is_dark = raw.get("gui", {}).get("dark_mode", False)

    # 恢复主题偏好
    if is_dark:
        dark.enable()

    def _toggle(e) -> None:
        if e.value:
            dark.enable()
        else:
            dark.disable()
        
        # 将最新的偏好写入 config 并保存
        current_raw = engine.get_raw_config()
        if "gui" not in current_raw:
            current_raw["gui"] = {}
        current_raw["gui"]["dark_mode"] = e.value
        engine.save_config(current_raw)

    with ui.header(elevated=True).classes("items-center justify-between"):
        with ui.row().classes("items-center gap-6"):
            ui.label(title).classes("text-h6")
            for label, href in _PAGES:
                ui.link(label, href).classes("text-white")
        with ui.row().classes("items-center gap-2"):
            ui.label("深色").classes("text-sm text-white")
            ui.switch(
                "",
                value=is_dark,
                on_change=_toggle,
            ).props("color=white")

