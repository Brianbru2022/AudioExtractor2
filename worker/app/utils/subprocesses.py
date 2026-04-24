from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


class ProcessError(RuntimeError):
    pass


def require_binary(name: str) -> str:
    resolved = shutil.which(name)
    if not resolved:
        raise ProcessError(f"Required binary not found on PATH: {name}")
    return resolved


def run_command(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ProcessError(
            f"Command failed ({completed.returncode}): {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return completed


def probe_json(command: list[str], cwd: Path | None = None) -> dict[str, Any]:
    completed = run_command(command, cwd=cwd)
    return json.loads(completed.stdout)
