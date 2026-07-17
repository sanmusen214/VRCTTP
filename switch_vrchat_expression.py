"""Automatically switch VRChat expressions with Shift+F1 through Shift+F8."""

import time

import keyboard
import psutil
import win32gui
import win32process


START_DELAY_SECONDS = 5
SWITCH_INTERVAL_SECONDS = 2
MODIFIER_SETTLE_SECONDS = 0.1
KEY_HOLD_SECONDS = 0.2
VRCHAT_EXECUTABLE = "vrchat.exe"


def foreground_process_name() -> str | None:
    """Return the executable name that owns the foreground window."""
    window = win32gui.GetForegroundWindow()
    if not window:
        return None

    try:
        _, process_id = win32process.GetWindowThreadProcessId(window)
        return psutil.Process(process_id).name()
    except (OSError, psutil.Error):
        return None


def send_left_shift_function_key(function_number: int) -> None:
    """Press and release Left Shift plus the requested function key."""
    function_key = f"f{function_number}"
    keyboard.press("left shift")
    try:
        time.sleep(MODIFIER_SETTLE_SECONDS)
        keyboard.press(function_key)
        time.sleep(KEY_HOLD_SECONDS)
        keyboard.release(function_key)
    finally:
        keyboard.release("left shift")


def main() -> None:
    print(
        f"Focus VRChat now. Switching starts in {START_DELAY_SECONDS} seconds."
    )
    time.sleep(START_DELAY_SECONDS)

    for function_number in range(1, 9):
        process_name = foreground_process_name()
        if process_name is None or process_name.casefold() != VRCHAT_EXECUTABLE:
            print(
                "Stopped: foreground process is "
                f"{process_name or 'unknown'}, not VRChat.exe."
            )
            return

        send_left_shift_function_key(function_number)
        print(f"Sent Left Shift + F{function_number}.")
        if function_number < 8:
            time.sleep(SWITCH_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
