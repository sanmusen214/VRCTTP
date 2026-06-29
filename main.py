"""
main.py — VRChat 实时翻译流 入口。

用法：
    # 使用默认配置文件，带 GUI
    python main.py

    # 指定配置文件，不启动 GUI
    python main.py --config my_config.json --no-gui

    # 仅列出可用音频设备
    python main.py --list-devices
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
import time

# 尽早加载 .env 文件，使 ${ENV_VAR} 占位符在配置解析前已注入环境变量
try:
    from dotenv import load_dotenv

    _env_path = os.path.join(os.path.dirname(__file__), ".env")
    if load_dotenv(_env_path, override=False):
        # override=False：已存在的系统环境变量优先，.env 仅补充缺失项
        print(f"[dotenv] 已加载: {_env_path}", flush=True)
except ImportError:
    pass  # python-dotenv 未安装时静默跳过，继续使用系统环境变量

# 配置日志（在导入其他模块前）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def _list_devices() -> None:
    """列出所有可用的音频设备。"""
    try:
        from modules.audio.sounddevice_backend import (
            default_input_device,
            default_output_device,
            list_input_devices,
            list_loopback_devices,
            list_output_devices,
        )

        print("\n=== 麦克风设备 ===")
        for device in list_input_devices():
            print(f"  [{device.index}] {device.label}")

        print("\n=== 环回/虚拟录音设备 ===")
        loopbacks = list_loopback_devices()
        if loopbacks:
            for device in loopbacks:
                print(f"  [{device.index}] {device.label}")
        else:
            print("  未发现系统暴露的 loopback 录音设备")

        print("\n=== 扬声器设备 ===")
        for device in list_output_devices():
            print(f"  [{device.index}] {device.label}")

        try:
            print(f"\n  默认扬声器: {default_output_device().label}")
            print(f"  默认麦克风: {default_input_device().label}")
        except Exception:
            pass
    except ImportError:
        print("请先安装 sounddevice: pip install sounddevice")
    print()


def _start_gui(engine, host: str, port: int, show: bool = False) -> threading.Thread:
    """在独立线程中启动 NiceGUI。"""
    from gui.app import create_app

    def _run():
        create_app(engine)
        from nicegui import ui
        ui.run(
            host=host,
            port=port,
            reload=False,
            show=show,
            title="VRChat 实时翻译流",
        )

    t = threading.Thread(target=_run, name="nicegui", daemon=True)
    t.start()
    return t


def main() -> None:
    parser = argparse.ArgumentParser(
        description="VRChat 实时翻译流",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config", default="config.json",
        help="配置文件路径（默认: config.json）"
    )
    parser.add_argument(
        "--no-gui", action="store_true",
        help="不启动 Web GUI"
    )
    parser.add_argument(
        "--list-devices", action="store_true",
        help="列出所有可用音频设备并退出"
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别（默认: INFO）"
    )
    args = parser.parse_args()

    # 应用日志级别
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    if args.list_devices:
        _list_devices()
        return

    # 导入引擎
    from core.engine import PipelineEngine

    engine = PipelineEngine(config_path=args.config)

    # 优雅退出处理
    stop_event = threading.Event()

    def _shutdown(signum=None, frame=None):
        logger.info("正在停止所有管道...")
        engine.stop_all()
        stop_event.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # 快速读取配置（只解析 JSON，不加载模型）
    try:
        engine.load_config()
    except Exception as e:
        logger.error("加载配置失败: %s", e)
        sys.exit(1)

    # 优先启动 GUI，让用户界面立即可用
    gui_cfg = engine.get_gui_config()
    gui_enabled = gui_cfg.get("enabled", True) and not args.no_gui
    if gui_enabled:
        gui_host = gui_cfg.get("host", "0.0.0.0")
        gui_port = int(gui_cfg.get("port", 8080))
        try:
            _start_gui(engine, gui_host, gui_port, show=True)
            logger.info("NiceGUI 已启动: http://localhost:%d", gui_port)
        except Exception:
            logger.exception("启动 GUI 失败，将以无 GUI 模式继续运行")

    # 在后台线程中执行耗时的 Pipeline 初始化（本地模型加载等）
    import gui.state as _gui_state

    def _init_pipelines():
        try:
            logger.info("后台初始化 Pipeline...")
            engine.build_all()
            engine.start_all()
            _gui_state.set_engine_ready()
            logger.info("所有管道已启动")
        except Exception as e:
            logger.error("管道初始化失败: %s", e)
            _gui_state.set_engine_error(str(e))

    if gui_enabled:
        threading.Thread(target=_init_pipelines, name="engine-init", daemon=True).start()
    else:
        # 无 GUI 模式：同步初始化
        try:
            engine.build_all()
            engine.start_all()
        except Exception as e:
            logger.error("加载配置失败: %s", e)
            sys.exit(1)
        logger.info("所有管道已启动，按 Ctrl+C 退出")

    # 主循环：等待退出信号
    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        _shutdown()


if __name__ == "__main__":
    main()
