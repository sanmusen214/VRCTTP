"""
Small sounddevice adapter for audio source modules.

The rest of the audio pipeline expects a context manager with a
``record(numframes)`` method returning float32 numpy samples.  This module
keeps that local contract stable while using sounddevice/PortAudio.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import sounddevice as sd

DEFAULT_SYSTEM_AUDIO_DEVICE = "__default_system_audio__"


@dataclass(frozen=True)
class AudioDevice:
    """Normalized view of a sounddevice device."""

    index: int
    name: str
    hostapi: str
    input_channels: int
    output_channels: int
    default_samplerate: int
    is_loopback: bool = False

    @property
    def label(self) -> str:
        return f"{self.name} [{self.hostapi}]"


def _hostapi_name(index: int) -> str:
    return str(sd.query_hostapis(index)["name"])


def _device_from_query(index: int, info: dict[str, Any], *, is_loopback: bool = False) -> AudioDevice:
    return AudioDevice(
        index=index,
        name=str(info["name"]),
        hostapi=_hostapi_name(int(info["hostapi"])),
        input_channels=int(info.get("max_input_channels") or 0),
        output_channels=int(info.get("max_output_channels") or 0),
        default_samplerate=int(info.get("default_samplerate") or 0),
        is_loopback=is_loopback,
    )


def _is_wasapi_device(device: AudioDevice) -> bool:
    return device.hostapi.lower() == "windows wasapi"


def _is_probable_loopback(device: AudioDevice) -> bool:
    name = device.name.lower()
    return any(
        token in name
        for token in (
            "loopback",
            "stereo mix",
            "what u hear",
            "立体声混音",
            "speaker",
            "speakers",
            "output",
            "扬声器",
        )
    )


def list_input_devices() -> list[AudioDevice]:
    """Return available microphone/input devices."""
    devices: list[AudioDevice] = []
    for idx, info in enumerate(sd.query_devices()):
        if int(info.get("max_input_channels") or 0) > 0:
            devices.append(_device_from_query(idx, info))
    return devices


def list_output_devices() -> list[AudioDevice]:
    """Return available speaker/output devices."""
    devices: list[AudioDevice] = []
    for idx, info in enumerate(sd.query_devices()):
        if int(info.get("max_output_channels") or 0) > 0:
            devices.append(_device_from_query(idx, info))
    return devices


def list_loopback_devices() -> list[AudioDevice]:
    """
    Return loopback-capable input devices exposed by PortAudio.

    sounddevice does not synthesize per-process loopback devices.  Some
    PortAudio builds expose WASAPI loopback capture devices directly; on
    other systems users may need to enable "Stereo Mix" or install a virtual
    audio cable.
    """
    devices: list[AudioDevice] = []
    for device in list_input_devices():
        if _is_probable_loopback(device):
            devices.append(AudioDevice(**{**device.__dict__, "is_loopback": True}))
    return devices


def default_input_device() -> AudioDevice:
    """Return the host API default input device, preferring WASAPI on Windows."""
    hostapis = sd.query_hostapis()
    wasapi = next((api for api in hostapis if str(api["name"]).lower() == "windows wasapi"), None)
    device_index = None
    if wasapi is not None and int(wasapi.get("default_input_device", -1)) >= 0:
        device_index = int(wasapi["default_input_device"])
    if device_index is None:
        device_index = int(sd.default.device[0])
    if device_index < 0:
        raise RuntimeError("未找到默认麦克风设备。")
    return _device_from_query(device_index, sd.query_devices(device_index))


def default_output_device() -> AudioDevice:
    """Return the host API default output device, preferring WASAPI on Windows."""
    hostapis = sd.query_hostapis()
    wasapi = next((api for api in hostapis if str(api["name"]).lower() == "windows wasapi"), None)
    device_index = None
    if wasapi is not None and int(wasapi.get("default_output_device", -1)) >= 0:
        device_index = int(wasapi["default_output_device"])
    if device_index is None:
        device_index = int(sd.default.device[1])
    if device_index < 0:
        raise RuntimeError("未找到默认扬声器设备。")
    return _device_from_query(device_index, sd.query_devices(device_index))


def find_input_device(device_name: str | None) -> AudioDevice:
    """Find an input device by exact name, label, index string, or substring."""
    if not device_name:
        return default_input_device()

    needle = device_name.strip().lower()
    devices = list_input_devices()
    for device in devices:
        if needle in (str(device.index), device.name.lower(), device.label.lower()):
            return device
    for device in devices:
        if needle in device.name.lower() or needle in device.label.lower():
            return device

    raise RuntimeError(f"找不到录音设备: {device_name}")


def find_loopback_device() -> AudioDevice:
    """Find the first loopback capture device exposed by PortAudio."""
    loopbacks = list_loopback_devices()
    if loopbacks:
        default_output = default_output_device()
        default_name = default_output.name.lower()
        for device in loopbacks:
            if device.name.lower() in default_name or default_name in device.name.lower():
                return device
        return loopbacks[0]

    raise RuntimeError(
        "未找到 sounddevice 可用的环回录音设备。请在 Windows 录音设备中启用“立体声混音”，"
        "或安装 Virtual Audio Cable/Voicemeeter 等虚拟音频设备；当前 PortAudio 构建未暴露 WASAPI loopback。"
    )


class SoundDeviceRecorder:
    """Context manager exposing a small ``record(numframes)`` API."""

    def __init__(self, device: AudioDevice, samplerate: int, blocksize: int, channels: int | None = None):
        self.device = device
        self.samplerate = int(samplerate)
        self.blocksize = int(blocksize)
        self.channels = int(channels or max(1, min(device.input_channels, 2)))
        self._stream: sd.InputStream | None = None

    def __enter__(self) -> "SoundDeviceRecorder":
        extra_settings = None
        if _is_wasapi_device(self.device):
            extra_settings = sd.WasapiSettings(auto_convert=True)
        self._stream = sd.InputStream(
            device=self.device.index,
            samplerate=self.samplerate,
            blocksize=self.blocksize,
            channels=self.channels,
            dtype="float32",
            extra_settings=extra_settings,
        )
        self._stream.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def record(self, numframes: int) -> np.ndarray:
        if self._stream is None:
            raise RuntimeError("录音流尚未启动。")
        data, overflowed = self._stream.read(int(numframes))
        if overflowed:
            # Keep the pipeline real-time; the next chunk will catch up.
            pass
        return np.asarray(data, dtype=np.float32)
