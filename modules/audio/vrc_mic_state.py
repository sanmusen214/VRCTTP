"""Shared VRChat microphone state listener based on OSC output."""

from __future__ import annotations

import logging
import threading

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer

logger = logging.getLogger(__name__)

VRC_MUTE_SELF_ADDRESS = "/avatar/parameters/MuteSelf"
VRC_OSC_OUTPUT_HOST = "127.0.0.1"
VRC_OSC_OUTPUT_PORT = 9001


class VRCMicStateMonitor:
    """Reference-counted OSC listener shared by all audio source modules."""

    def __init__(
        self,
        host: str = VRC_OSC_OUTPUT_HOST,
        port: int = VRC_OSC_OUTPUT_PORT,
    ) -> None:
        self._host = host
        self._port = port
        self._lock = threading.Lock()
        self._muted: bool | None = None
        self._users = 0
        self._server: ThreadingOSCUDPServer | None = None
        self._thread: threading.Thread | None = None

    def acquire(self) -> None:
        """Start listening on the first active subscriber."""
        with self._lock:
            if self._users > 0:
                self._users += 1
                return

            dispatcher = Dispatcher()
            dispatcher.map(VRC_MUTE_SELF_ADDRESS, self._on_mute_self)
            server = ThreadingOSCUDPServer((self._host, self._port), dispatcher)
            thread = threading.Thread(
                target=server.serve_forever,
                name="vrc-mic-state-osc",
                daemon=True,
            )
            self._server = server
            self._thread = thread
            self._muted = None
            self._users = 1
            thread.start()
            logger.info(
                "正在监听 VRChat 麦克风状态 %s（%s:%d）",
                VRC_MUTE_SELF_ADDRESS,
                self._host,
                self._port,
            )

    def release(self) -> None:
        """Stop the listener after the last subscriber leaves."""
        with self._lock:
            if self._users <= 0:
                return
            self._users -= 1
            if self._users > 0:
                return
            server = self._server
            thread = self._thread
            self._server = None
            self._thread = None
            self._muted = None

        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)
        logger.info("已停止监听 VRChat 麦克风状态")

    def is_mic_open(self) -> bool | None:
        """Return True=open, False=muted, None=no state received yet."""
        with self._lock:
            if self._muted is None:
                return None
            return not self._muted

    @property
    def listening_address(self) -> tuple[str, int] | None:
        """Return the bound UDP address while the monitor is running."""
        with self._lock:
            if self._server is None:
                return None
            host, port = self._server.server_address
            return str(host), int(port)

    def _on_mute_self(self, _address: str, value) -> None:
        if isinstance(value, bool):
            muted = value
        elif isinstance(value, (int, float)) and value in (0, 1):
            muted = bool(value)
        else:
            logger.warning("忽略无效的 VRChat MuteSelf OSC 值: %r", value)
            return

        with self._lock:
            changed = muted != self._muted
            self._muted = muted
        if changed:
            logger.info("VRChat 麦克风状态: %s", "关闭" if muted else "开启")


vrc_mic_state_monitor = VRCMicStateMonitor()
