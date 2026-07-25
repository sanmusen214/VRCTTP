"""Windows 桌面半透明翻译历史窗口消费者。"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from typing import Any

from core.module import PacketConsumerModule, ParamType
from core.packet import MessagePacket
from modules.utils.multilingual_aggregation import MultilingualPacketAggregator

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _OverlayUpdate:
    key: tuple[str | None, Any]
    text: str


@dataclass(frozen=True)
class _OverlayConfig:
    title: str = "VRChat 实时翻译"
    opacity: float = 0.78
    font_size: int = 20
    width: int = 720
    height: int = 360
    topmost: bool = True
    history_size: int = 200


@dataclass(frozen=True)
class _OverlayShow:
    pass


class DesktopOverlayService:
    """进程级 Tk 窗口单例，生命周期独立于所有 Pipeline。"""

    _instance: "DesktopOverlayService | None" = None
    _instance_lock = threading.Lock()

    @classmethod
    def instance(cls) -> "DesktopOverlayService":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self) -> None:
        if type(self)._instance is not None:
            raise RuntimeError("DesktopOverlayService 必须通过 instance() 获取")
        self._config = _OverlayConfig()
        self._commands: queue.Queue[
            _OverlayUpdate | _OverlayConfig | _OverlayShow | None
        ] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._visible = threading.Event()
        self._lock = threading.Lock()

    def start(self, config: dict | None = None) -> None:
        """启动一次；重复调用只在线更新配置，不重建窗口。"""
        if config is not None:
            self.configure(config)
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._ready.clear()
            self._thread = threading.Thread(
                target=self._run, name="desktop-overlay", daemon=True
            )
            self._thread.start()
        self._ready.wait(timeout=3.0)

    def configure(self, config: dict) -> None:
        new_config = _config_from_dict(config)
        self._config = new_config
        if self._thread and self._thread.is_alive():
            self._commands.put(new_config)

    def submit(self, update: _OverlayUpdate) -> None:
        self._commands.put(update)

    def ensure_visible(self, config: dict | None = None) -> bool:
        """仅当窗口隐藏或线程已退出时恢复窗口；已可见时不做任何操作。"""
        if config is not None:
            self.configure(config)
        if not self._thread or not self._thread.is_alive():
            self.start()
            return True
        if self._visible.is_set():
            return False
        self._commands.put(_OverlayShow())
        return True

    def stop(self) -> None:
        """仅供软件整体退出调用。"""
        with self._lock:
            thread = self._thread
            if not thread:
                return
            self._commands.put(None)
        if thread is not threading.current_thread():
            thread.join(timeout=3.0)
        with self._lock:
            self._thread = None

    def _run(self) -> None:
        try:
            import tkinter as tk
            from tkinter import font

            config = self._config
            root = tk.Tk()
            root.title(config.title)
            root.geometry(f"{config.width}x{config.height}")
            root.minsize(240, 120)
            root.attributes("-alpha", config.opacity)
            root.attributes("-topmost", config.topmost)
            root.configure(background="#111111")
            self._visible.set()

            text_font = font.Font(
                family="Microsoft YaHei UI", size=config.font_size
            )
            scrollbar = tk.Scrollbar(root)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            text_widget = tk.Text(
                root,
                wrap=tk.WORD,
                background="#111111",
                foreground="#ffffff",
                insertbackground="#ffffff",
                relief=tk.FLAT,
                borderwidth=8,
                yscrollcommand=scrollbar.set,
                font=text_font,
            )
            text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar.config(command=text_widget.yview)
            text_widget.configure(state=tk.DISABLED)

            entries: list[tuple[tuple[str | None, Any], str]] = []
            history_size = config.history_size

            def redraw() -> None:
                text_widget.configure(state=tk.NORMAL)
                text_widget.delete("1.0", tk.END)
                text_widget.insert("1.0", "\n\n".join(text for _, text in entries))
                text_widget.configure(state=tk.DISABLED)
                text_widget.yview_moveto(0.0)

            def poll_updates() -> None:
                nonlocal history_size
                should_close = False
                changed = False
                while True:
                    try:
                        command = self._commands.get_nowait()
                    except queue.Empty:
                        break
                    if command is None:
                        should_close = True
                        break
                    if isinstance(command, _OverlayConfig):
                        root.title(command.title)
                        root.attributes("-alpha", command.opacity)
                        root.attributes("-topmost", command.topmost)
                        text_font.configure(size=command.font_size)
                        history_size = command.history_size
                        del entries[history_size:]
                        changed = True
                        continue
                    if isinstance(command, _OverlayShow):
                        root.deiconify()
                        root.lift()
                        self._visible.set()
                        continue
                    entries[:] = [
                        (key, text) for key, text in entries if key != command.key
                    ]
                    entries.insert(0, (command.key, command.text))
                    del entries[history_size:]
                    changed = True
                if changed:
                    redraw()
                if should_close:
                    root.destroy()
                    return
                root.after(50, poll_updates)

            def hide_window() -> None:
                root.withdraw()
                self._visible.clear()

            root.protocol("WM_DELETE_WINDOW", hide_window)
            self._ready.set()
            root.after(50, poll_updates)
            root.mainloop()
        except Exception:
            logger.exception("桌面悬浮翻译窗口运行失败")
            self._ready.set()
        finally:
            self._visible.clear()


def _config_from_dict(config: dict) -> _OverlayConfig:
    return _OverlayConfig(
        title=str(config.get("title", "VRChat 实时翻译")),
        opacity=min(1.0, max(0.1, float(config.get("opacity", 0.78)))),
        font_size=max(8, int(config.get("font_size", 20))),
        width=max(240, int(config.get("width", 720))),
        height=max(120, int(config.get("height", 360))),
        topmost=bool(config.get("topmost", True)),
        history_size=max(1, int(config.get("history_size", 200))),
    )


class DesktopOverlayConsumer(PacketConsumerModule):
    """将完整句子的聚合翻译结果显示在可缩放半透明窗口中。"""

    @classmethod
    def require_attributes_in_packages(cls) -> list[dict]:
        return [
            {"name": "text_original", "must_have": False, "description": "原文"},
            {"name": "text_translated", "must_have": False, "description": "译文"},
            {"name": "target_lang", "must_have": False, "description": "目标语言"},
        ]

    @classmethod
    def add_attributes_in_packages(cls) -> list[dict]:
        return []

    @classmethod
    def get_config_attributes(cls) -> list[dict]:
        return [
            {"name": "opacity", "type": ParamType.Float, "default": 0.78, "required": False, "description": "窗口整体不透明度（0.1-1.0）", "selectable": None, "min": 0.1, "max": 1.0},
            {"name": "font_size", "type": ParamType.Int, "default": 20, "required": False, "description": "窗口内文字大小", "selectable": None, "min": 8, "max": 72},
            {"name": "width", "type": ParamType.Int, "default": 720, "required": False, "description": "窗口初始宽度", "selectable": None, "min": 240, "max": 3840},
            {"name": "height", "type": ParamType.Int, "default": 360, "required": False, "description": "窗口初始高度", "selectable": None, "min": 120, "max": 2160},
            {"name": "topmost", "type": ParamType.Bool, "default": True, "required": False, "description": "窗口是否保持置顶", "selectable": None},
            {"name": "history_size", "type": ParamType.Int, "default": 200, "required": False, "description": "窗口中保留的完整句子数量", "selectable": None, "min": 1, "max": 5000},
            {"name": "group_by", "type": ParamType.String, "default": "timestamp_中间件-GUI输入文字", "required": False, "description": "多语言分组 key，如 timestamp_中间件-GUI输入文字", "selectable": None},
        ]

    def __init__(self, module_id: str, config: dict) -> None:
        super().__init__(module_id, config)
        self._aggregator = MultilingualPacketAggregator(
            group_by=str(
                config.get("group_by", "timestamp_中间件-GUI输入文字")
            )
        )
        self._window = DesktopOverlayService.instance()

    def process_packet(self, packet: MessagePacket) -> list[MessagePacket]:
        if packet.is_partial:
            return [packet]
        result = self._aggregator.add(packet)
        if result is None or not result.translated:
            return [packet]

        lines = [result.original] if result.original else []
        lines.extend(result.translations.values())
        text = "\n".join(line for line in lines if line)
        if text:
            self._window.submit(_OverlayUpdate(result.display_key, text))
        return [packet]
