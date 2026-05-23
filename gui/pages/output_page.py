"""
实时翻译输出页面。

订阅 TerminalConsumer 的 GUI 回调（通过 gui.state.output_buffer），
每秒刷新展示最新 200 条翻译记录。
"""
from __future__ import annotations

from nicegui import ui

import gui.state as state
from gui.components.nav import create_nav


def register(app) -> None:  # noqa: ARG001

    @ui.page("/output")
    async def output_page() -> None:
        ui.page_title("实时翻译输出")
        create_nav()

        with ui.column().classes("w-full max-w-4xl mx-auto q-pa-md gap-4"):
            ui.label("实时翻译输出").classes("text-h5")
            ui.label("最新 200 条（最新在最上方） · 每 1 秒刷新").classes("text-caption text-grey")

            container = ui.column().classes("w-full gap-1")

            def _snapshot() -> list[dict]:
                with state.output_lock:
                    return list(reversed(list(state.output_buffer)))

            async def refresh() -> None:
                container.clear()
                rows = _snapshot()
                with container:
                    if not rows:
                        ui.label("暂无翻译输出，请确认至少一条管道正在运行…").classes("text-grey")
                    else:
                        for row in rows:
                            with ui.card().classes("w-full q-py-xs q-px-sm"):
                                with ui.row().classes("items-center gap-2 flex-wrap"):
                                    ui.badge(row["pipeline"], color="blue")
                                    ui.label(row["original"])
                                    ui.label("→").classes("text-grey")
                                    ui.label(row["translated"]).classes("text-bold")

            await refresh()
            ui.timer(1.0, refresh)
