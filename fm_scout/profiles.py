"""Game version profile registry.

FM24 struct layouts and AOB signatures differ between game builds, so the
scanner is parameterised by a :class:`VersionProfile`.  This module owns the
list of known builds and any *user-supplied* profiles dropped as JSON files
into ``game_profiles/`` next to ``main.py`` (or the directory given by the
``FM_SCOUT_PROFILE_DIR`` environment variable).

Profile files extend, never replace, the built-in profiles.  Any field can be
omitted and the matching value from the built-in default profile is used.
Offsets may be written as decimal numbers or as hex strings.
"""

import dataclasses
import json
import logging
import os
from pathlib import Path

from .offsets import (
    ATTRIBUTE_BYTE_OFFSETS,
    DEFAULT_PROFILE,
    ClubOffsets,
    StructOffsets,
    VersionProfile,
)

logger = logging.getLogger("fm_scout.profiles")

__all__ = ["get_profiles", "load_user_profiles", "profile_dir"]

_STRUCT_FIELDS = {f.name for f in dataclasses.fields(StructOffsets)}
_CLUB_FIELDS = {f.name for f in dataclasses.fields(ClubOffsets)}
_KNOWN_ATTRS = set(ATTRIBUTE_BYTE_OFFSETS)


def _to_int(value, default: int, name: str = "") -> int:
    """Coerce JSON numbers / hex strings onto an int, like config parsers."""
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        s = value.strip()
        try:
            return int(s, 0)
        except ValueError:
            try:
                return int(s, 16)
            except ValueError:
                pass
    logger.warning("ignoring non-numeric offset %s=%r", name, value)
    return default


def _fill(obj, data: dict | None) -> None:
    """Apply ``data`` onto a dataclass instance, ignoring unknown keys."""
    if not data:
        return
    for name, value in data.items():
        if hasattr(obj, name) and isinstance(value, (int, str, bool)):
            try:
                setattr(obj, name, _to_int(value, getattr(obj, name), name))
            except Exception:  # pragma: no cover - defensive
                logger.exception("bad offset %s", name)


def _profile_from_dict(data: dict) -> VersionProfile | None:
    default = DEFAULT_PROFILE
    label = str(data.get("label") or "").strip()
    if not label:
        logger.warning("skipping game profile without a label")
        return None

    aob = dict(default.aob)
    raw_aob = data.get("aob")
    if isinstance(raw_aob, dict):
        aob.update({k: str(v) for k, v in raw_aob.items() if isinstance(v, str)})

    struct = _copy_struct(data.get("struct"))
    club = _copy_club(data.get("club"))

    attr_bytes = dict(default.attribute_byte_offsets)
    raw_attrs = data.get("attribute_byte_offsets")
    if isinstance(raw_attrs, dict):
        for name, value in raw_attrs.items():
            if name in _KNOWN_ATTRS:
                attr_bytes[name] = _to_int(value, attr_bytes[name], name)
            else:
                logger.warning("unknown attribute in profile %s: %s", label, name)

    return VersionProfile(
        label=label,
        aob=aob,
        person_db_offset=_to_int(
            data.get("person_db_offset"), default.person_db_offset
        ),
        table_container_offset=_to_int(
            data.get("table_container_offset"), default.table_container_offset
        ),
        struct=struct,
        attribute_byte_offsets=attr_bytes,
        club=club,
    )


def _copy_struct(data: dict | None) -> StructOffsets:
    struct = _copy_defaults(StructOffsets, DEFAULT_PROFILE.struct, _STRUCT_FIELDS)
    _fill(struct, data)
    return struct


def _copy_club(data: dict | None) -> ClubOffsets:
    club = _copy_defaults(ClubOffsets, DEFAULT_PROFILE.club, _CLUB_FIELDS)
    _fill(club, data)
    return club


def _copy_defaults(cls, source, fields: set[str]):
    return cls(**{name: getattr(source, name) for name in fields})


def profile_dir() -> Path:
    root = Path(__file__).resolve().parent.parent
    env = os.environ.get("FM_SCOUT_PROFILE_DIR")
    return Path(env).expanduser() if env else root / "game_profiles"


def load_user_profiles(directory: Path | None = None) -> list[VersionProfile]:
    """Load user-supplied profile JSON files from *directory*."""
    directory = Path(directory) if directory else profile_dir()
    if not directory.is_dir():
        return []
    profiles: list[VersionProfile] = []
    for path in sorted(directory.glob("*.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("skipping bad profile %s: %s", path.name, e)
            continue
        profile = _profile_from_dict(data)
        if profile is not None:
            profiles.append(profile)
            logger.info("loaded game profile '%s' from %s", profile.label, path.name)
    return profiles


def get_profiles() -> list[VersionProfile]:
    """Built-in profile first, then user overrides."""
    return [DEFAULT_PROFILE, *load_user_profiles()]