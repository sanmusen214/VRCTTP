"""
首页 — 管道状态概览，支持 enabled 切换。

每个管道卡片显示运行状态，开关仅修改 config（不重载），需点击「重载所有配置」使更改生效。
"""
from __future__ import annotations

import os
import subprocess
from urllib.parse import quote

from nicegui import app as nicegui_app, ui

import gui.state as state
from gui.components.nav import create_nav
from gui.update_notice import build_update_notice
from runtime_paths import all_minimum_env_values_empty
from runtime_paths import application_dir
from version import release_info, version_str


def register(app) -> None:  # noqa: ARG001

    @ui.page("/")
    async def home() -> None:
        if state.consume_initial_env_redirect() and all_minimum_env_values_empty():
            ui.navigate.to("/env")
            return
        ui.page_title("VRCTTP")
        engine = state.get_engine()

        updater_path = os.path.join(application_dir(), "VRCTTP_UPDATE.exe")
        update_dialog = ui.dialog()
        with update_dialog, ui.card().classes("w-full").style("width:min(980px, 92vw); max-width:980px"):
            update_title_label = ui.label("版本更新说明").classes("text-h5")
            update_version_label = ui.label().classes("text-subtitle1 text-bold")
            update_release_notes = ui.markdown("").classes("w-full")
            with ui.row().classes("justify-end w-full gap-2"):
                ui.button("关闭", on_click=update_dialog.close).props("flat")

                def _launch_updater() -> None:
                    if not os.path.isfile(updater_path):
                        ui.notify(f"找不到更新器：{updater_path}", type="negative")
                        return
                    try:
                        subprocess.Popen(
                            [updater_path],
                            cwd=application_dir(),
                            creationflags=subprocess.CREATE_NEW_CONSOLE,
                            close_fds=True,
                        )
                        ui.notify("更新器已启动，请按更新器提示操作", type="positive")
                    except Exception as exc:
                        ui.notify(f"启动更新器失败：{exc}", type="negative")

                update_action_button = ui.button(
                    "立即更新",
                    icon="system_update_alt",
                    on_click=_launch_updater,
                    color="orange",
                )
                update_action_button.set_visibility(False)

        ui.add_css("""
        @keyframes update-border-pulse {
          0%, 100% { box-shadow: 0 0 0 0 rgba(255, 152, 0, .7); }
          50% { box-shadow: 0 0 0 5px rgba(255, 152, 0, 0); }
        }
        .update-available-badge {
          border: 2px solid #ff9800 !important;
          border-radius: 6px !important;
          animation: update-border-pulse 1.6s ease-in-out infinite;
        }
        """)

        update_badge = None

        def _apply_update_notice() -> bool:
            notice = build_update_notice(
                state.get_update_info(),
                current_version=version_str,
                local_release_notes=release_info,
            )
            update_title_label.set_text(notice.title)
            update_version_label.set_text(notice.version_text)
            update_release_notes.set_content(notice.release_notes)
            update_action_button.set_visibility(notice.has_new_version)
            update_title_label.classes(
                add="text-orange-9" if notice.has_new_version else None,
                remove=None if notice.has_new_version else "text-orange-9",
            )
            if update_badge is not None:
                update_badge.set_text(notice.badge_text)
                update_badge.props(remove="color=orange color=primary")
                update_badge.props(
                    add="color=orange" if notice.has_new_version else "color=primary"
                )
                if notice.has_new_version:
                    update_badge.classes(add="update-available-badge")
                else:
                    update_badge.classes(remove="update-available-badge")
            return notice.has_new_version

        def _open_update_notice() -> None:
            _apply_update_notice()
            update_dialog.open()

        def _render_update_badge() -> None:
            nonlocal update_badge
            update_badge = ui.button(
                "版本说明",
                icon="info",
                on_click=_open_update_notice,
                color="primary",
            ).props("dense no-caps")

        create_nav(right_content=_render_update_badge)
        _apply_update_notice()

        update_dialog_opened = False

        def _refresh_update_notice() -> None:
            nonlocal update_dialog_opened
            has_new_version = _apply_update_notice()
            if has_new_version and not update_dialog_opened:
                update_dialog_opened = True
                update_dialog.open()

        with ui.column().classes("w-full max-w-4xl mx-auto q-pa-md gap-4"):
            with ui.column().classes("gap-1"):
                ui.label(f"VRCTTP 当前版本：{version_str}").classes("text-h4 text-bold")
                ui.label("QQ 交流群：964670098").classes("text-subtitle1 text-grey-7")
                ui.label("务必在VRC内开启OSC，加速器改用路由模式，选择你所使用的麦克风作为系统默认麦克风").style("color: red;")
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

                    sync_pipelines = engine.get_vrc_mic_sync_pipeline_names()
                    if sync_pipelines:
                        with ui.card().classes("w-full bg-orange-1 q-pa-sm"):
                            with ui.row().classes("items-start gap-2 no-wrap"):
                                ui.icon("warning", color="orange").classes("q-mt-xs")
                                with ui.column().classes("gap-0"):
                                    ui.label("VRChat 麦克风状态同步已启用").classes(
                                        "text-bold text-orange-9"
                                    )
                                    ui.label(
                                        "翻译启动后，请在游戏内切换一次麦克风开/关，"
                                        "以便程序收到初始状态。默认会按麦克风静音处理。"
                                    ).classes("text-orange-9")
                                    ui.label(
                                        f"相关管道：{', '.join(sync_pipelines)}"
                                    ).classes("text-caption text-orange-8")

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

                                with ui.row().classes("items-center gap-2"):
                                    ui.button(
                                        icon="edit",
                                        color="primary",
                                        on_click=lambda _, pipeline_id=pid: ui.navigate.to(
                                            f"/pipelines?edit_pipeline={quote(pipeline_id, safe='')}"
                                        ),
                                    ).props("flat round dense").tooltip("编辑管道")

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
            ui.timer(1.0, _refresh_update_notice)
