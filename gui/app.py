"""
NiceGUI Web 界面 — VRChat 实时翻译流控制台。

功能页面：
  - Dashboard  : 各 Pipeline 状态 + 启停按钮
  - Live Output: 实时翻译输出（订阅 TerminalConsumer 的 GUI 回调）
  - Config     : JSON 配置文件编辑器（保存 + 重启引擎）
  - Devices    : 列出可用音频设备（供复制设备名到配置）

使用 nicegui 的 ui.timer + asyncio 刷新状态，不需要 websocket 手动管理。
"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.engine import PipelineEngine

logger = logging.getLogger(__name__)

# 最多保留最近 N 条翻译记录
MAX_OUTPUT_LINES = 200


def create_app(engine: "PipelineEngine") -> None:
    """
    注册 NiceGUI 路由和界面。
    此函数在 ui.run() 之前调用，用于定义所有页面。
    """
    from nicegui import ui

    # 共享输出缓冲（GUI 回调写入，UI 定时器读取）
    output_buffer: deque[dict] = deque(maxlen=MAX_OUTPUT_LINES)
    output_lock = threading.Lock()

    # 注册 TerminalConsumer 的 GUI 回调
    from modules.consumer.terminal import register_gui_callback

    def _on_translation(pipeline_name: str, original: str, translated: str) -> None:
        with output_lock:
            output_buffer.append({
                "pipeline": pipeline_name,
                "original": original,
                "translated": translated,
            })

    register_gui_callback(_on_translation)

    # ------------------------------------------------------------------
    # 主页面
    # ------------------------------------------------------------------

    @ui.page("/")
    async def index_page():
        ui.page_title("VRChat 实时翻译流")

        with ui.header(elevated=True).classes("items-center"):
            ui.label("VRChat 实时翻译流").classes("text-h6 text-white")
            ui.space()
            ui.link("Dashboard", "/").classes("text-white")
            ui.link("实时输出", "/output").classes("text-white ml-4")
            ui.link("配置编辑", "/config").classes("text-white ml-4")
            ui.link("音频设备", "/devices").classes("text-white ml-4")

        ui.label("管道状态").classes("text-h5 q-mt-md")

        status_container = ui.column().classes("w-full")

        async def refresh_status():
            status_container.clear()
            statuses = engine.get_status()
            if not statuses:
                with status_container:
                    ui.label("没有已启用的管道。请检查 config.json 并确保至少一条 pipeline 的 enabled=true。").classes("text-grey")
                return
            with status_container:
                for s in statuses:
                    with ui.card().classes("w-full q-mb-sm"):
                        with ui.row().classes("items-center"):
                            color = "green" if s["status"] == "running" else "red"
                            ui.badge(s["status"], color=color)
                            ui.label(f"[{s['id']}] {s['name']}").classes("text-bold ml-2")
                        with ui.row():
                            ui.label(f"音频源: {s['audio_source_type']}").classes("text-caption")
                            ui.label(f"翻译: {s['translation_type']}").classes("text-caption ml-4")
                            ui.label(f"消费: {', '.join(s['consumer_types'])}").classes("text-caption ml-4")
                        with ui.row():
                            pid = s["id"]
                            if s["status"] == "running":
                                ui.button(
                                    "停止",
                                    on_click=lambda p=pid: (engine.stop_pipeline(p), refresh_status()),
                                    color="red",
                                ).props("size=sm")
                            else:
                                ui.button(
                                    "启动",
                                    on_click=lambda p=pid: (engine.start_pipeline(p), refresh_status()),
                                    color="green",
                                ).props("size=sm")

        await refresh_status()
        ui.timer(3.0, refresh_status)

        with ui.row().classes("q-mt-md"):
            ui.button(
                "全部停止",
                on_click=lambda: (engine.stop_all(), refresh_status()),
                color="red",
            )
            ui.button(
                "重载配置并重启",
                on_click=lambda: (engine.reload_config(), refresh_status()),
                color="primary",
            )

    # ------------------------------------------------------------------
    # 实时输出页面
    # ------------------------------------------------------------------

    @ui.page("/output")
    async def output_page():
        ui.page_title("实时翻译输出")

        with ui.header(elevated=True).classes("items-center"):
            ui.label("VRChat 实时翻译流 — 实时输出").classes("text-h6 text-white")
            ui.space()
            ui.link("← 返回 Dashboard", "/").classes("text-white")

        ui.label("实时翻译输出").classes("text-h5 q-mt-md")
        ui.label("最新 200 条记录（新的在最上面）").classes("text-caption text-grey")

        log_container = ui.column().classes("w-full")

        def _snapshot():
            with output_lock:
                return list(reversed(list(output_buffer)))

        async def refresh_output():
            log_container.clear()
            rows = _snapshot()
            with log_container:
                if not rows:
                    ui.label("暂无翻译输出，请确认管道正在运行...").classes("text-grey")
                else:
                    for row in rows:
                        with ui.card().classes("w-full q-mb-xs"):
                            with ui.row().classes("items-center"):
                                ui.badge(row["pipeline"], color="blue")
                                ui.label(row["original"]).classes("ml-2")
                                ui.label("→").classes("mx-2 text-grey")
                                ui.label(row["translated"]).classes("text-bold")

        await refresh_output()
        ui.timer(1.0, refresh_output)

    # ------------------------------------------------------------------
    # 配置编辑页面
    # ------------------------------------------------------------------

    @ui.page("/config")
    async def config_page():
        ui.page_title("配置编辑")

        with ui.header(elevated=True).classes("items-center"):
            ui.label("VRChat 实时翻译流 — 配置").classes("text-h6 text-white")
            ui.space()
            ui.link("← 返回 Dashboard", "/").classes("text-white")

        ui.label("配置文件编辑").classes("text-h5 q-mt-md")
        ui.label("注意：保存后需点击「重载配置」才能生效。API Key 建议使用 ${OPENAI_API_KEY} 环境变量占位。").classes("text-caption text-orange")

        status_label = ui.label("").classes("text-caption")

        raw_cfg = engine.get_raw_config()
        initial_text = json.dumps(raw_cfg, ensure_ascii=False, indent=2)

        editor = ui.textarea(value=initial_text).classes("w-full font-mono").props("rows=30 outlined")

        async def save_config():
            try:
                parsed = json.loads(editor.value)
                engine.save_config(parsed)
                status_label.set_text("✓ 配置已保存").classes("text-green")
            except json.JSONDecodeError as e:
                status_label.set_text(f"✗ JSON 格式错误: {e}").classes("text-red")

        async def save_and_reload():
            try:
                parsed = json.loads(editor.value)
                engine.save_config(parsed)
                engine.reload_config()
                status_label.set_text("✓ 配置已保存并重载").classes("text-green")
            except json.JSONDecodeError as e:
                status_label.set_text(f"✗ JSON 格式错误: {e}").classes("text-red")
            except Exception as e:
                status_label.set_text(f"✗ 重载失败: {e}").classes("text-red")

        with ui.row():
            ui.button("保存配置", on_click=save_config, color="primary")
            ui.button("保存并重载", on_click=save_and_reload, color="green")

    # ------------------------------------------------------------------
    # 音频设备页面
    # ------------------------------------------------------------------

    @ui.page("/devices")
    async def devices_page():
        ui.page_title("音频设备")

        with ui.header(elevated=True).classes("items-center"):
            ui.label("VRChat 实时翻译流 — 音频设备").classes("text-h6 text-white")
            ui.space()
            ui.link("← 返回 Dashboard", "/").classes("text-white")

        ui.label("可用音频设备").classes("text-h5 q-mt-md")
        ui.label("复制设备名到 config.json 的 device_name / process_name 字段中使用。").classes("text-caption text-grey")

        try:
            import warnings
            import soundcard as sc
            warnings.filterwarnings("ignore", category=RuntimeWarning)

            def _device_section(title: str, devices: list):
                ui.label(title).classes("text-h6 q-mt-md")
                if not devices:
                    ui.label("（无设备）").classes("text-grey")
                    return
                with ui.column().classes("w-full"):
                    for d in devices:
                        with ui.card().classes("w-full q-mb-xs"):
                            with ui.row().classes("items-center"):
                                ui.label(d.name).classes("flex-grow")
                                ui.button(
                                    "复制",
                                    on_click=lambda name=d.name: ui.clipboard.write(name),
                                ).props("size=sm flat")

            mics = sc.all_microphones(include_loopback=False)
            loopbacks = [m for m in sc.all_microphones(include_loopback=True) if m.isloopback]
            speakers = sc.all_speakers()

            _device_section("麦克风", list(mics))
            _device_section("环回（Loopback）设备", loopbacks)
            _device_section("扬声器", list(speakers))

        except ImportError:
            ui.label("soundcard 未安装，无法列出设备。请运行: pip install soundcard").classes("text-red")
        except Exception as e:
            ui.label(f"获取设备列表失败: {e}").classes("text-red")
