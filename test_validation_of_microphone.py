"""Minimal microphone capture validation script.

Records 15 seconds from the current system default microphone with
sounddevice, saves the audio in the current directory, and waits for Enter
before exiting.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
import traceback

import numpy as np
import sounddevice as sd
import soundfile as sf


SAMPLE_RATE = 16000
RECORD_SECONDS = 6


def _default_input_device() -> tuple[int, dict]:
    hostapis = sd.query_hostapis()
    wasapi = next((api for api in hostapis if str(api["name"]).lower() == "windows wasapi"), None)
    device_index = None
    if wasapi is not None and int(wasapi.get("default_input_device", -1)) >= 0:
        device_index = int(wasapi["default_input_device"])
    if device_index is None:
        device_index = int(sd.default.device[0])
    if device_index < 0:
        raise RuntimeError("未找到默认麦克风设备。")
    return device_index, sd.query_devices(device_index)


def _hostapi_name(device_info: dict) -> str:
    return str(sd.query_hostapis(int(device_info["hostapi"]))["name"])


def _record_with_stream(
    device_index: int,
    device_info: dict,
    sample_rate: int,
    channels: int,
) -> np.ndarray:
    extra_settings = None
    if _hostapi_name(device_info).lower() == "windows wasapi":
        extra_settings = sd.WasapiSettings(auto_convert=True)

    frames_total = RECORD_SECONDS * sample_rate
    frames_read = 0
    chunks: list[np.ndarray] = []
    progress_marks = {5, 10}

    with sd.InputStream(
        device=device_index,
        samplerate=sample_rate,
        channels=channels,
        dtype="float32",
        blocksize=0,
        extra_settings=extra_settings,
    ) as stream:
        start = time.monotonic()
        while frames_read < frames_total:
            remaining = frames_total - frames_read
            block_frames = min(1024, remaining)
            data, overflowed = stream.read(block_frames)
            if overflowed:
                logging.warning("录音缓冲区发生 overflow，继续录制")
            chunks.append(data.copy())
            frames_read += len(data)
            elapsed = int(time.monotonic() - start)
            if elapsed in progress_marks:
                logging.info("录制中... %.1f/%ss", frames_read / sample_rate, RECORD_SECONDS)
                progress_marks.remove(elapsed)

    return np.concatenate(chunks, axis=0)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    device_index, device_info = _default_input_device()
    device_name = str(device_info["name"])
    channels = max(1, min(int(device_info.get("max_input_channels") or 1), 2))
    sample_rate = SAMPLE_RATE

    logging.info("当前默认麦克风: [%s] %s", device_index, device_name)
    logging.info("开始录制 %s 秒音频，采样率=%sHz，通道数=%s", RECORD_SECONDS, sample_rate, channels)

    try:
        audio = _record_with_stream(device_index, device_info, sample_rate, channels)
    except sd.PortAudioError as exc:
        default_rate = int(device_info.get("default_samplerate") or 0)
        if default_rate <= 0 or default_rate == sample_rate:
            raise
        logging.warning("使用 %sHz 打开麦克风失败: %s", sample_rate, exc)
        logging.warning("改用设备默认采样率 %sHz 重新录制", default_rate)
        sample_rate = default_rate
        audio = _record_with_stream(device_index, device_info, sample_rate, channels)

    output_path = Path.cwd() / f"microphone_validation_{datetime.now():%Y%m%d_%H%M%S}.wav"
    sf.write(output_path, audio, sample_rate)
    logging.info("录制结束，音频已保存: %s", output_path)

    input("按回车结束程序...")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logging.error("程序发生未处理异常: %s", exc)
        traceback.print_exc()
        input("按回车退出...")
