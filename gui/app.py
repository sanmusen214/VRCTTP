"""
NiceGUI Web 界面入口 — 多页面架构。

模块结构：
    gui/state.py           — 全局状态（engine 引用、输出缓冲区、输出锁）
    gui/components/nav.py  — 共享导航栏（含深色/浅色实时切换）
    gui/components/module_form.py — 基于 ParamType 的动态模块参数表单
    gui/pages/home.py          — / 首页：管道状态与 enabled 切换
    gui/pages/output_page.py   — /output 实时翻译输出
    gui/pages/pipelines_page.py— /pipelines 管道管理（图结构、enabled 切换）
    gui/pages/modules_page.py  — /modules 模块目录（config schema 展示）
    gui/pages/config_page.py   — /config 原始 JSON 配置编辑器
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.engine import PipelineEngine

logger = logging.getLogger(__name__)


def create_app(engine: "PipelineEngine") -> None:
    """
    初始化全局 GUI 状态，注册 TerminalConsumer 回调，并注册所有 NiceGUI 页面路由。
    在 ui.run() 之前调用。
    """
    import gui.state as state
    state.init(engine)

    # 将 TerminalConsumer 的实时翻译输出写入共享缓冲区
    from modules.consumer.terminal import register_gui_callback

    def _on_translation(pipeline_name: str, original: str, translated: str) -> None:
        with state.output_lock:
            state.output_buffer.append({
                "pipeline": pipeline_name,
                "original": original,
                "translated": translated,
            })

    register_gui_callback(_on_translation)

    # 注册所有页面路由
    from nicegui import app
    from gui.pages import home, output_page, pipelines_page, modules_page, config_page, env_page, input_page

    home.register(app)
    output_page.register(app)
    pipelines_page.register(app)
    modules_page.register(app)
    config_page.register(app)
    env_page.register(app)
    input_page.register(app)

    logger.info("GUI 页面已注册（7 个路由）")
