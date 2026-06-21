from __future__ import annotations

import time
import unittest

from pythonosc.udp_client import SimpleUDPClient

from modules.audio.vrc_mic_state import (
    VRC_MUTE_SELF_ADDRESS,
    VRCMicStateMonitor,
)


def _wait_for_state(monitor: VRCMicStateMonitor, expected: bool) -> None:
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if monitor.is_mic_open() is expected:
            return
        time.sleep(0.01)
    raise AssertionError(f"未在超时前收到麦克风状态 {expected}")


class VRCMicStateMonitorTest(unittest.TestCase):
    def test_receives_vrchat_mute_self_over_osc(self) -> None:
        monitor = VRCMicStateMonitor(port=0)
        monitor.acquire()
        try:
            address = monitor.listening_address
            self.assertIsNotNone(address)
            client = SimpleUDPClient(*address)
            try:
                client.send_message(VRC_MUTE_SELF_ADDRESS, False)
                _wait_for_state(monitor, True)

                client.send_message(VRC_MUTE_SELF_ADDRESS, True)
                _wait_for_state(monitor, False)
            finally:
                client._sock.close()  # python-osc does not expose a public close method
        finally:
            monitor.release()

    def test_is_shared_until_last_release(self) -> None:
        monitor = VRCMicStateMonitor(port=0)
        monitor.acquire()
        monitor.acquire()
        address = monitor.listening_address
        self.assertIsNotNone(address)

        monitor.release()
        self.assertEqual(monitor.listening_address, address)

        monitor.release()
        self.assertIsNone(monitor.listening_address)


if __name__ == "__main__":
    unittest.main()
