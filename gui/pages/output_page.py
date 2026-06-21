"""
文字输入与实时翻译输出页面。

订阅 TerminalConsumer 的 GUI 回调（通过 gui.state.output_buffer），
每秒刷新展示最新 200 条翻译记录。
"""
from __future__ import annotations

from nicegui import ui

import gui.state as state
from gui.components.nav import create_nav
from modules.input.text_input import TextInput


def register(app) -> None:  # noqa: ARG001

    @ui.page("/output")
    async def output_page() -> None:
        ui.page_title("文字输入与实时输出")
        create_nav()

        with ui.column().classes("w-full max-w-4xl mx-auto q-pa-md gap-4").style("min-height: calc(100vh - 80px)"):
            with ui.row().classes("items-center justify-between w-full"):
                ui.label("文字输入").classes("text-h5")
                ui.button(
                    "刷新实例", icon="refresh",
                    on_click=lambda: draw_inputs.refresh(),
                ).props("flat")

            ui.label(
                "每个输入框对应一个活跃的 TextInput 模块实例；按 Enter 或点击发送。"
            ).classes("text-caption text-grey")

            @ui.refreshable
            def draw_inputs() -> None:
                instances = TextInput._instances
                if not instances:
                    with ui.card().classes("w-full"):
                        ui.label(
                            "暂无活跃的 TextInput 实例。请创建 text_input 模块，"
                            "接入管道后在首页重载配置。"
                        ).classes("text-grey")
                    return

                for module in instances.values():
                    with ui.card().classes("w-full q-pa-sm"):
                        ui.label(
                            f"{module.display_name} · {module.config.get('pipeline_id', '?')}"
                        ).classes("text-subtitle2 text-bold")

                        def _make_send(m: TextInput):
                            def _send(inp: ui.input) -> None:
                                text = (inp.value or "").strip()
                                if not text:
                                    return
                                m.submit_text(text)
                                ui.notify(f"已发送到 {m.display_name!r}: {text!r}", type="positive")
                                inp.value = ""
                            return _send

                        send_fn = _make_send(module)
                        with ui.row().classes("items-center gap-2 w-full"):
                            inp = ui.input(
                                placeholder="输入原文，按 Enter 发送…",
                            ).classes("flex-grow").props("outlined dense clearable")
                            inp.on("keydown.enter", lambda _, i=inp, send=send_fn: send(i))
                            ui.button(
                                "发送", icon="send", color="primary",
                                on_click=lambda _, i=inp, send=send_fn: send(i),
                            ).props("dense")

            draw_inputs()

            ui.separator()
            ui.label("实时翻译输出").classes("text-h5")
            ui.label("最新 200 条（最新在最上方） · 每 1 秒刷新").classes("text-caption text-grey")

            container = ui.column().classes("w-full gap-1 flex-grow")

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
