"""
共享导航栏组件，包含深色/浅色主题实时切换。

使用 app.storage.user 跨页面保持主题偏好（需要 ui.run() 传入 storage_secret）。
"""
from __future__ import annotations

from nicegui import app, ui

_PAGES = [
    ("首页",     "/"),
    ("实时输出", "/output"),
    ("管道管理", "/pipelines"),
    ("模块目录", "/modules"),
    ("配置编辑", "/config"),
    ("环境变量", "/env"),
]


def create_nav(title: str = "VRChat 实时翻译流") -> None:
    """在当前页面顶部渲染导航栏（含深色/浅色切换开关）。"""
    dark = ui.dark_mode()

    # 从 user storage 恢复主题偏好
    if app.storage.user.get("dark_mode", False):
        dark.enable()

    def _toggle(e) -> None:
        if e.value:
            dark.enable()
        else:
            dark.disable()
        app.storage.user["dark_mode"] = e.value

    with ui.header(elevated=True).classes("items-center justify-between"):
        with ui.row().classes("items-center gap-6"):
            ui.label(title).classes("text-h6")
            for label, href in _PAGES:
                ui.link(label, href).classes("text-white")
        with ui.row().classes("items-center gap-2"):
            ui.label("深色").classes("text-sm text-white")
            ui.switch(
                "",
                value=app.storage.user.get("dark_mode", False),
                on_change=_toggle,
            ).props("color=white")
