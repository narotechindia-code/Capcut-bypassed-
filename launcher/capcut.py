from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional


COMMON_PATHS = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "CapCut" / "Apps" / "CapCut.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "CapCut" / "CapCut.exe",
    Path(os.environ.get("PROGRAMFILES", "")) / "CapCut" / "Apps" / "CapCut.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", "")) / "CapCut" / "Apps" / "CapCut.exe",
]


def find_capcut(explicit: Optional[str] = None) -> Optional[Path]:
    """Find a CapCut executable without modifying the machine."""
    candidates = []
    if explicit:
        candidates.append(Path(explicit).expanduser())

    path_value = shutil.which("CapCut.exe")
    if path_value:
        candidates.append(Path(path_value))

    candidates.extend(COMMON_PATHS)

    # Search only likely CapCut directories; avoid an expensive whole-disk scan.
    roots = [
        Path(os.environ.get("LOCALAPPDATA", "")),
        Path(os.environ.get("PROGRAMFILES", "")),
        Path(os.environ.get("PROGRAMFILES(X86)", "")),
    ]
    for root in roots:
        if root.exists():
            candidates.extend(root.glob("CapCut*/**/CapCut.exe"))

    seen = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        if resolved.is_file() and resolved.name.lower() == "capcut.exe":
            return resolved
    return None


def launch_capcut(executable: Path, environment: dict[str, str]) -> int:
    """Launch CapCut and wait for it to exit."""
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(
        [str(executable)],
        cwd=str(executable.parent),
        env=environment,
        creationflags=creationflags,
    )
    return process.wait()
