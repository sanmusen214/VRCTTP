"""
首页 — 管道状态概览，支持 enabled 切换。

每个管道卡片显示运行状态，开关仅修改 config（不重载），需点击「重载所有配置」使更改生效。
"""
from __future__ import annotations

from nicegui import app as nicegui_app, ui

import gui.state as state
from gui.components.nav import create_nav


def register(app) -> None:  # noqa: ARG001

    @ui.page("/")
    async def home() -> None:
        ui.page_title("VRCTTP")
        create_nav()
        engine = state.get_engine()

        with ui.column().classes("w-full max-w-4xl mx-auto q-pa-md gap-4"):
            ui.label("管道状态").classes("text-h5")

            init_banner = ui.column().classes("w-full")
            status_col = ui.column().classes("w-full gap-2")

            async def refresh() -> None:
                # ── 引擎初始化状态横幅 ──────────────────────────────
                init_banner.clear()
                init_status, init_error = state.get_engine_init_status()
                with init_banner:
                    if init_status == "initializing":
                        with ui.card().classes("w-full bg-blue-1 q-pa-sm"):
                            with ui.row().classes("items-center gap-2"):
                                ui.spinner(size="sm", color="blue")
                                ui.label("Pipeline 正在后台初始化，本地模型加载中，请稍候...").classes("text-blue-8")
                    elif init_status == "error":
                        with ui.card().classes("w-full bg-red-1 q-pa-sm"):
                            ui.label(f"❌ Pipeline 初始化失败：{init_error}").classes("text-negative")
                    elif init_status == "ready":
                        # 模型目录缺失检测（仅初始化完成后才检查）
                        missing = engine.get_missing_model_warnings()
                        for msg in missing:
                            with ui.card().classes("w-full bg-red-1 q-pa-sm"):
                                ui.icon("warning", color="negative").classes("q-mr-sm")
                                ui.label(f"⚠ 本地语音识别模型缺失：{msg}").classes("text-negative")

                # ── 管道列表 ─────────────────────────────────────────
                status_col.clear()
                statuses = engine.get_status()
                raw = engine.get_raw_config()
                # Build id→status map from running pipelines
                running_map: dict[str, dict] = {s["id"]: s for s in statuses}
                pipelines = [
                    p for p in raw.get("pipelines", [])
                    if isinstance(p, dict) and "id" in p
                ]

                with status_col:
                    if not pipelines:
                        ui.label("配置中没有任何管道，请在「配置编辑」页中添加。").classes("text-grey")
                        return

                    for pipeline in pipelines:
                        pid = pipeline["id"]
                        name = pipeline.get("name", pid)
                        enabled = pipeline.get("enabled", False)
                        running = pid in running_map
                        status_text = "running" if running else ("enabled-pending" if enabled else "stopped")
                        status_color = "positive" if running else ("warning" if enabled else "negative")

                        with ui.card().classes("w-full"):
                            with ui.row().classes("items-center justify-between w-full"):
                                with ui.row().classes("items-center gap-3"):
                                    ui.badge(status_text, color=status_color)
                                    ui.label(f"[{pid}] {name}").classes("text-bold")

                                # Use closure to capture pid
                                def _make_toggle(pipeline_id: str):
                                    async def _toggle(e) -> None:
                                        r = engine.get_raw_config()
                                        for p in r.get("pipelines", []):
                                            if isinstance(p, dict) and p.get("id") == pipeline_id:
                                                p["enabled"] = e.value
                                        engine.save_config(r)
                                        ui.notify(
                                            f"{'启用' if e.value else '禁用'} {pipeline_id}，配置已保存（需点击「重载所有配置」生效）",
                                            type="positive" if e.value else "warning",
                                        )
                                        await refresh()
                                    return _toggle

                                ui.switch(
                                    "启用",
                                    value=enabled,
                                    on_change=_make_toggle(pid),
                                )

                            # Show detail row for running pipelines
                            if pid in running_map:
                                s = running_map[pid]
                                with ui.row().classes("text-caption text-grey gap-4 q-mt-xs"):
                                    ui.label(f"音频源: {s['audio_source_type']}")
                                    ui.label(f"翻译/处理: {s['translation_type']}")
                                    ui.label(f"消费者: {', '.join(s['consumer_types'])}")

            await refresh()

            with ui.row().classes("gap-3 q-mt-sm"):
                async def _reload_all() -> None:
                    engine.reload_config()
                    ui.notify("已重载所有配置", type="positive")
                    await refresh()

                ui.button("重载所有配置", on_click=_reload_all, color="primary")

            ui.timer(5.0, refresh)
