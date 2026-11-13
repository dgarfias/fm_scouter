from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    name: str
    cmdline: str
    exe_path: str


@dataclass(frozen=True)
class MemoryRegion:
    start: int
    end: int
    permissions: str
    path: str


def find_fm_process() -> ProcessInfo | None:
    """Scan /proc for the Wine/Proton process running fm.exe.

    Launchers and steam.exe also mention fm.exe in their arguments and may
    use wine-preloader. Only accept processes whose own executable, argv[0],
    or process name identifies fm.exe. Wine drive letters are not fixed.
    """
    def is_fm_executable(path: str) -> bool:
        return path.replace("\\", "/").rsplit("/", 1)[-1].lower() == "fm.exe"

    candidates: list[ProcessInfo] = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                raw = f.read()
            if not raw:
                continue
            argv0 = raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
            cmdline = raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
            try:
                exe_path = os.readlink(f"/proc/{pid}/exe")
            except OSError:
                exe_path = ""
            try:
                with open(f"/proc/{pid}/comm", "r") as f:
                    name = f.read().strip()
            except OSError:
                name = ""
            if not any(is_fm_executable(value) for value in (argv0, exe_path, name)):
                continue
            candidates.append(ProcessInfo(pid=pid, name=name, cmdline=cmdline, exe_path=exe_path))
        except (OSError, PermissionError):
            continue

    if not candidates:
        return None

    return candidates[-1]


def get_memory_regions(pid: int) -> list[MemoryRegion]:
    """Parse /proc/{pid}/maps and return readable memory regions."""
    regions: list[MemoryRegion] = []
    maps_path = f"/proc/{pid}/maps"
    try:
        with open(maps_path, "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 2:
                    continue
                addr_range, perms = parts[0], parts[1]
                if "r" not in perms:
                    continue
                path = parts[-1] if len(parts) >= 6 else ""
                start_s, end_s = addr_range.split("-", 1)
                start = int(start_s, 16)
                end = int(end_s, 16)
                regions.append(MemoryRegion(start=start, end=end, permissions=perms, path=path))
    except OSError as e:
        raise RuntimeError(f"Cannot read {maps_path}: {e}") from e
    return regions
