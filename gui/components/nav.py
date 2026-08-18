"""共享导航栏组件。"""
from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

_PAGES = [
    ("首页",     "/"),
    ("文字输入与输出", "/output"),
    ("管道管理", "/pipelines"),
    ("模块目录", "/modules"),
    ("配置编辑", "/config"),
    ("环境变量", "/env"),
]


def create_nav(
    title: str = "VRCTTP 实时翻译",
    right_content: Callable[[], None] | None = None,
) -> None:
    """在当前页面顶部渲染导航栏，并强制使用亮色主题。"""
    ui.dark_mode(False)

    with ui.header(elevated=True).classes("items-center justify-between"):
        with ui.row().classes("items-center gap-6"):
            ui.label(title).classes("text-h6")
            for label, href in _PAGES:
                ui.link(label, href).classes("text-white")
        with ui.row().classes("items-center gap-2"):
            if right_content is not None:
                right_content()

