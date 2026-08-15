from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional


COMMON_PATHS = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "CapCut" / "Apps" / "CapCut.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "CapCut" / "CapCut.exe",
    Path(os.environ.get("PROGRAMFILES", "")) / "CapCut" / "Apps" / "CapCut.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", "")) / "CapCut" / "Apps" / "CapCut.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "CapCut" / "CapCut.exe",
]


def _candidate_roots() -> list[Path]:
    roots = []
    for value in (
        os.environ.get("LOCALAPPDATA"),
        os.environ.get("PROGRAMFILES"),
        os.environ.get("PROGRAMFILES(X86)"),
    ):
        if value:
            roots.append(Path(value))
    return roots


def find_capcut(explicit: Optional[str] = None) -> Optional[Path]:
    """Find an installed CapCut executable without modifying the machine."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())

    path_value = shutil.which("CapCut.exe")
    if path_value:
        candidates.append(Path(path_value))

    candidates.extend(COMMON_PATHS)

    # CapCut versions can place the executable below a versioned directory.
    # Keep the search bounded to the standard application roots.
    for root in _candidate_roots():
        if not root.exists():
            continue
        for pattern in (
            "CapCut*/**/CapCut.exe",
            "CapCut/**/CapCut.exe",
            "Programs/CapCut/**/CapCut.exe",
        ):
            try:
                candidates.extend(root.glob(pattern))
            except (OSError, ValueError):
                pass

    # Also inspect the uninstall registry indirectly through PowerShell. This
    # catches installations registered by an installer in a non-standard folder.
    ps = shutil.which("powershell.exe")
    if ps:
        command = r"Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -like '*CapCut*' } | Select-Object -ExpandProperty InstallLocation"
        try:
            result = subprocess.run(
                [ps, "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            for line in result.stdout.splitlines():
                location = line.strip()
                if location:
                    candidates.append(Path(location) / "CapCut.exe")
                    candidates.extend(Path(location).glob("**/CapCut.exe"))
        except (OSError, subprocess.SubprocessError):
            pass

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
