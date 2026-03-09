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

    Multiple processes contain 'fm.exe' in their cmdline (Steam reaper,
    Proton launcher, etc.).  We want the actual Wine process whose cmdline
    starts with a Wine-style path (``Z:\\...\\fm.exe``) or whose exe
    points to a wine/proton binary.
    """
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
            cmdline = raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
            if "fm.exe" not in cmdline.lower():
                continue
            try:
                exe_path = os.readlink(f"/proc/{pid}/exe")
            except OSError:
                exe_path = ""
            try:
                with open(f"/proc/{pid}/comm", "r") as f:
                    name = f.read().strip()
            except OSError:
                name = ""
            candidates.append(ProcessInfo(pid=pid, name=name, cmdline=cmdline, exe_path=exe_path))
        except (OSError, PermissionError):
            continue

    if not candidates:
        return None

    for c in candidates:
        if c.cmdline.startswith("Z:\\") or c.cmdline.startswith("z:\\"):
            return c

    for c in candidates:
        if "wine" in c.exe_path.lower() or "proton" in c.exe_path.lower():
            return c

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
