from __future__ import annotations

import subprocess
import sys


def test_importing_local_stt_module_does_not_load_funasr_runtime() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import modules.translation.LocalSTTModel; "
                "assert 'funasr' not in sys.modules; "
                "assert 'torch' not in sys.modules"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
