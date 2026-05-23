"""
文字输入页面 — /input

显示所有当前活跃的 TextInput 模块实例，每个实例对应一个输入框。
用户在输入框中输入文字后按 Enter 或点击「发送」，文字即作为原文
沿对应 pipeline 向下游（翻译、消费者等）流动。

注意：实例仅在 pipeline 启动后才会出现。请先在首页点击「重载所有配置」。
"""
from __future__ import annotations

from nicegui import ui

import gui.state as state
from gui.components.nav import create_nav
from modules.input.text_input import TextInput


def register(app) -> None:  # noqa: ARG001

    @ui.page("/input")
    def input_page() -> None:
        ui.page_title("文字输入")
        create_nav()

        with ui.column().classes("w-full max-w-3xl mx-auto q-pa-md gap-4"):
            with ui.row().classes("items-center justify-between w-full"):
                ui.label("文字输入").classes("text-h5")
                ui.button(
                    "刷新实例", icon="refresh",
                    on_click=lambda: draw_inputs.refresh(),
                ).props("flat")

            ui.label(
                "每个输入框对应一个活跃的 TextInput 模块实例。"
                "输入文字后按 Enter 或点击「发送」，文字将作为原文沿 pipeline 传递。"
            ).classes("text-caption text-grey")

            @ui.refreshable
            def draw_inputs() -> None:
                instances = TextInput._instances
                if not instances:
                    with ui.card().classes("w-full"):
                        ui.label(
                            "暂无活跃的 TextInput 实例。"
                            "请确认已在模块列表中创建类型为 text_input 的实例，"
                            "并在首页点击「重载所有配置」启动 pipeline。"
                        ).classes("text-grey")
                    return

                for mod_id, module in instances.items():
                    with ui.card().classes("w-full q-pa-sm"):
                        ui.label(
                            f"{module._ref_id}  ·  {module.config.get('pipeline_id', '?')}"
                        ).classes("text-subtitle2 text-bold")
                        ui.label(f"module_id: {mod_id}").classes(
                            "text-caption text-grey"
                        )

                        def _make_send(m: TextInput):
                            def _send(inp: ui.input) -> None:
                                text = inp.value.strip()
                                if not text:
                                    return
                                m.submit_text(text)
                                ui.notify(
                                    f"已发送到 {m._ref_id!r}: {text!r}",
                                    type="positive",
                                )
                                inp.value = ""

                            return _send

                        send_fn = _make_send(module)

                        with ui.row().classes("items-center gap-2 w-full"):
                            inp = ui.input(
                                placeholder="输入原文，按 Enter 发送…",
                            ).classes("flex-grow").props("outlined dense clearable")
                            inp.on("keydown.enter", lambda _, i=inp: send_fn(i))
                            ui.button(
                                "发送", icon="send", color="primary",
                                on_click=lambda _, i=inp: send_fn(i),
                            ).props("dense")

            draw_inputs()
