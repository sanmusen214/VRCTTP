"""
配置编辑页面。

提供原始 JSON 配置文件的编辑器（textarea），支持保存和保存+重载两种操作。
API Key 建议以 ${ENV_VAR} 占位符引用系统环境变量。
"""
from __future__ import annotations

import json

from nicegui import ui

import gui.state as state
from gui.components.nav import create_nav


def register(app) -> None:  # noqa: ARG001

    @ui.page("/config")
    async def config_page() -> None:
        ui.page_title("配置编辑")
        create_nav()
        engine = state.get_engine()

        with ui.column().classes("w-full max-w-4xl mx-auto q-pa-md gap-4"):
            ui.label("配置编辑").classes("text-h5")
            ui.label(
                "注意：API Key 建议使用 ${ENV_VAR} 环境变量占位。"
                "保存后需点击「保存并重载」才能生效。"
            ).classes("text-caption text-orange")

            status = ui.label("").classes("text-caption")

            raw = engine.get_raw_config()
            initial = json.dumps(raw, ensure_ascii=False, indent=2)

            editor = ui.textarea(value=initial).classes("w-full font-mono").props(
                "rows=32 outlined"
            )

            async def _save() -> None:
                try:
                    parsed = json.loads(editor.value)
                    engine.save_config(parsed)
                    status.set_text("✓ 已保存")
                    status.classes(remove="text-negative", add="text-positive")
                except json.JSONDecodeError as e:
                    status.set_text(f"✗ JSON 格式错误: {e}")
                    status.classes(remove="text-positive", add="text-negative")

            async def _save_and_reload() -> None:
                try:
                    parsed = json.loads(editor.value)
                    engine.save_config(parsed)
                    engine.reload_config()
                    status.set_text("✓ 已保存并重载所有管道")
                    status.classes(remove="text-negative", add="text-positive")
                except json.JSONDecodeError as e:
                    status.set_text(f"✗ JSON 格式错误: {e}")
                    status.classes(remove="text-positive", add="text-negative")
                except Exception as e:
                    status.set_text(f"✗ 重载失败: {e}")
                    status.classes(remove="text-positive", add="text-negative")

            with ui.row().classes("gap-3"):
                ui.button("保存", on_click=_save, color="primary")
                ui.button("保存并重载", on_click=_save_and_reload, color="positive")
