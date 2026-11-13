"""Player attribute writing for FM24.

Writes attributes, personality and ability values back into the running
FM24 process.

Memory addresses are only valid for the load they were scanned in, so
they are never persisted: exported profiles carry attribute *values*
only, and every write re-validates that the record still holds the same
player (by uid) before touching it.
"""

import json
import logging
import os
import struct

from .memory import MemoryReader, _init_vm_readv
from .offsets import (
    ATTRIBUTE_BYTE_OFFSETS,
    PERSONALITY_NAMES,
    POSITION_NAMES,
    STRUCT_OFFSETS,
    StructOffsets,
)
from .player import Player

logger = logging.getLogger("fm_scout")

EXPORT_FORMAT = "fm-scout-player-attributes"
EXPORT_VERSION = 1

ATTRIBUTE_FIELDS: tuple[str, ...] = tuple(ATTRIBUTE_BYTE_OFFSETS.keys())

# Display scale bounds. FM shows 1-20; 0 is "not set" and never written.
MIN_ATTRIBUTE = 1
MAX_ATTRIBUTE = 20
MAX_ABILITY = 200

# Names accepted by import on top of the canonical field names, so a
# hand-written file can use the wording the game's UI uses.
_FIELD_ALIASES: dict[str, str] = {
    "penalty": "penalty_taking",
    "penalties": "penalty_taking",
    "jumping": "jumping_reach",
    "free_kicks": "free_kick_taking",
    "freekicks": "free_kick_taking",
    "corner": "corners",
    "natural_fitness": "natural_fitness",
    "work_rate": "work_rate",
    "workrate": "work_rate",
    "off_the_ball": "off_the_ball",
    "one_on_one": "one_on_ones",
    "rushing_out_tendency": "rushing_out",
    "command_of_the_area": "command_of_area",
    "acceleration": "acceleration",
    "accel": "acceleration",
    "injury_prone": "injury_proneness",
    "important_match": "important_matches",
}

_ABILITY_ALIASES: dict[str, str] = {
    "ca": "current_ability",
    "current_ability": "current_ability",
    "pa": "potential_ability",
    "potential_ability": "potential_ability",
}


class PlayerWriteError(Exception):
    """Raised when a write cannot be performed safely."""


def normalize_field(name: str) -> str | None:
    """Map a loose attribute name onto a canonical field name.

    Returns ``None`` when the name matches no known attribute.
    """
    key = str(name).strip().lower().replace(" ", "_").replace("-", "_")
    while "__" in key:
        key = key.replace("__", "_")
    if key in ATTRIBUTE_BYTE_OFFSETS:
        return key
    return _FIELD_ALIASES.get(key)


def normalize_position(name: str) -> str | None:
    """Map a loose position name onto its canonical POSITION_NAMES entry."""
    key = str(name).strip().upper().replace(" ", "").replace("_", "")
    for canonical in POSITION_NAMES:
        if canonical == key:
            return canonical
    return None


def normalize_personality(name: str) -> str | None:
    """Map a loose personality name onto its canonical PERSONALITY_NAMES entry."""
    key = str(name).strip().lower().replace("_", " ")
    for canonical in PERSONALITY_NAMES:
        if canonical.lower() == key:
            return canonical
    return None


class MemoryWriter(MemoryReader):
    """A MemoryReader that also opens the process for writing."""

    def open(self):
        self._fd = os.open(f"/proc/{self.pid}/mem", os.O_RDWR)
        try:
            _init_vm_readv()
            self.has_batch_read = True
        except Exception:
            self.has_batch_read = False

    def write_bytes(self, address: int, data: bytes) -> bool:
        if address < 0 or address > 0x7FFFFFFFFFFF:
            return False
        try:
            return os.pwrite(self._fd, data, address) == len(data)
        except (OSError, OverflowError) as e:
            logger.warning("write failed at 0x%X: %s", address, e)
            return False


class PlayerWriter:
    """Applies attribute edits to a live player record."""

    def __init__(
        self,
        writer: MemoryWriter,
        struct_offsets: StructOffsets = STRUCT_OFFSETS,
        attribute_byte_offsets: dict[str, int] | None = None,
    ):
        self.writer = writer
        self.so = struct_offsets
        if attribute_byte_offsets is None:
            attribute_byte_offsets = ATTRIBUTE_BYTE_OFFSETS
        self.attr_bytes = attribute_byte_offsets

    # ------------------------------------------------------------------ #
    #  Validation                                                         #
    # ------------------------------------------------------------------ #

    def validate(self, player: Player):
        """Confirm the record at *player*'s address is still that player.

        Addresses are captured at scan time.  Reloading a save or quitting
        the game invalidates them, and writing to a stale address would
        corrupt an unrelated object, so this must pass before any write.
        """
        so = self.so
        reader = self.writer

        if not player.address or not player.plao_address:
            raise PlayerWriteError("player has no memory address (run a scan first)")

        vtable = reader.read_pointer(player.address)
        if not vtable:
            raise PlayerWriteError("player record is no longer readable")
        if player.vtable and vtable != player.vtable:
            raise PlayerWriteError("player record has moved (re-scan required)")

        type_info = reader.read_pointer(vtable - 8)
        offset_val = reader.read_uint32(type_info + 4) if type_info else None
        if offset_val != so.player_offset:
            raise PlayerWriteError("address does not hold a player object")

        uid = reader.read_uint32(player.address + so.duni)
        if uid != player.uid:
            raise PlayerWriteError(
                f"player identity mismatch (expected uid {player.uid}, found {uid})"
            )

    # ------------------------------------------------------------------ #
    #  Writes                                                             #
    # ------------------------------------------------------------------ #

    def _attr_address(self, player: Player, field: str) -> int:
        return (
            player.plao_address
            + self.so.patr
            + self.attr_bytes[field]
        )

    def write_attribute(self, player: Player, field: str, display_value: int) -> bool:
        """Write one 1-20 attribute, converting to the raw 1-100 scale."""
        if field not in self.attr_bytes:
            raise PlayerWriteError(f"unknown attribute: {field}")
        value = max(MIN_ATTRIBUTE, min(MAX_ATTRIBUTE, int(display_value)))
        raw = value * self.so.attr_scale
        if not self.writer.write_bytes(self._attr_address(player, field), bytes([raw])):
            return False
        setattr(player.attributes, field, value)
        return True

    def write_position(self, player: Player, name: str, value: int) -> bool:
        """Write one position rating (stored unscaled, 1-20)."""
        try:
            index = POSITION_NAMES.index(name)
        except ValueError:
            raise PlayerWriteError(f"unknown position: {name}") from None
        val = max(MIN_ATTRIBUTE, min(MAX_ATTRIBUTE, int(value)))
        addr = player.plao_address + self.so.ppos + index
        if not self.writer.write_bytes(addr, bytes([val])):
            return False
        player.positions[name] = val
        return True

    def write_personality(self, player: Player, name: str, value: int) -> bool:
        """Write one personality value (stored unscaled, 1-20)."""
        try:
            index = PERSONALITY_NAMES.index(name)
        except ValueError:
            raise PlayerWriteError(f"unknown personality attribute: {name}") from None
        val = max(MIN_ATTRIBUTE, min(MAX_ATTRIBUTE, int(value)))
        addr = player.address + self.so.pada + index
        if not self.writer.write_bytes(addr, bytes([val])):
            return False
        player.personality[name] = val
        return True

    def _write_ability(self, player: Player, offset: int, value: int) -> int | None:
        """Write a CA/PA value, matching the scale the save already uses.

        Some builds store ability multiplied by 100 (7500 == 75).  The
        stored value is read first so the same encoding is written back.
        """
        val = max(0, min(MAX_ABILITY, int(value)))
        addr = player.plao_address + offset
        current = self.writer.read_bytes(addr, 2)
        if current is None or len(current) < 2:
            raise PlayerWriteError("could not read current ability value")
        raw_current = struct.unpack("<h", current)[0]
        scaled = raw_current > 250
        raw_new = val * 100 if scaled else val
        if not self.writer.write_bytes(addr, struct.pack("<h", raw_new)):
            return None
        return val

    def write_current_ability(self, player: Player, value: int) -> bool:
        written = self._write_ability(player, self.so.pcab, value)
        if written is None:
            return False
        player.current_ability = written
        return True

    def write_potential_ability(self, player: Player, value: int) -> bool:
        written = self._write_ability(player, self.so.ppab, value)
        if written is None:
            return False
        player.potential_ability = written
        return True

    def apply(
        self,
        player: Player,
        attributes: dict[str, int] | None = None,
        positions: dict[str, int] | None = None,
        personality: dict[str, int] | None = None,
        current_ability: int | None = None,
        potential_ability: int | None = None,
    ) -> tuple[int, list[str]]:
        """Apply a set of edits to *player*.

        Returns ``(written_count, failures)``.  The in-memory Player is
        updated for every value that was written successfully.
        """
        self.validate(player)

        written = 0
        failures: list[str] = []

        for field, value in (attributes or {}).items():
            if self.write_attribute(player, field, value):
                written += 1
            else:
                failures.append(field)

        for name, value in (positions or {}).items():
            if self.write_position(player, name, value):
                written += 1
            else:
                failures.append(name)

        for name, value in (personality or {}).items():
            if self.write_personality(player, name, value):
                written += 1
            else:
                failures.append(name)

        if current_ability is not None:
            if self.write_current_ability(player, current_ability):
                written += 1
            else:
                failures.append("current_ability")

        if potential_ability is not None:
            if self.write_potential_ability(player, potential_ability):
                written += 1
            else:
                failures.append("potential_ability")

        logger.info(
            "applied %d value(s) to %s (uid %d), %d failure(s)",
            written,
            player.display_name,
            player.uid,
            len(failures),
        )
        return written, failures


# ====================================================================== #
#  Import / export                                                        #
# ====================================================================== #


def build_export(
    player: Player,
    attributes: dict[str, int],
    positions: dict[str, int],
    personality: dict[str, int],
    current_ability: int,
    potential_ability: int,
) -> dict:
    """Build the JSON-serialisable profile for *player*.

    Values only -- no memory addresses, so a profile stays valid across
    game restarts and can be applied to a different player.
    """
    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "player": {
            "uid": player.uid,
            "name": player.display_name,
            "club": player.club,
        },
        "current_ability": current_ability,
        "potential_ability": potential_ability,
        "attributes": {f: int(v) for f, v in attributes.items()},
        "positions": {n: int(v) for n, v in positions.items()},
        "personality": {n: int(v) for n, v in personality.items()},
    }


def export_to_file(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


ImportedProfile = tuple[
    dict[str, int], dict[str, int], dict[str, int], int | None, int | None
]

_SECTIONS = ("attributes", "positions", "personality")
_METADATA_KEYS = ("player", "format", "version")


def parse_import(data: dict) -> ImportedProfile:
    """Parse an imported profile.

    Accepts the exported layout and also a flat ``{name: value}`` mapping,
    so a file can be written by hand.  Unknown names are ignored.
    Returns ``(attributes, positions, personality, ca, pa)``.
    """
    if not isinstance(data, dict):
        raise PlayerWriteError("file does not contain a player profile")

    attributes: dict[str, int] = {}
    positions: dict[str, int] = {}
    personality: dict[str, int] = {}
    current_ability: int | None = None
    potential_ability: int | None = None

    def clamp(val: int) -> int:
        return max(MIN_ATTRIBUTE, min(MAX_ATTRIBUTE, val))

    def take(name: str, value, section: str | None = None) -> None:
        nonlocal current_ability, potential_ability
        try:
            val = int(value)
        except (TypeError, ValueError):
            return

        if section == "positions":
            pos = normalize_position(name)
            if pos:
                positions[pos] = clamp(val)
            return
        if section == "personality":
            pers = normalize_personality(name)
            if pers:
                personality[pers] = clamp(val)
            return
        if section == "attributes":
            field = normalize_field(name)
            if field:
                attributes[field] = clamp(val)
            return

        key = str(name).strip().lower().replace(" ", "_").replace("-", "_")
        ability = _ABILITY_ALIASES.get(key)
        if ability == "current_ability":
            current_ability = max(0, min(MAX_ABILITY, val))
            return
        if ability == "potential_ability":
            potential_ability = max(0, min(MAX_ABILITY, val))
            return
        field = normalize_field(name)
        if field:
            attributes[field] = clamp(val)
            return
        pers = normalize_personality(name)
        if pers:
            personality[pers] = clamp(val)
            return
        pos = normalize_position(name)
        if pos:
            positions[pos] = clamp(val)

    for section in _SECTIONS:
        block = data.get(section)
        if isinstance(block, dict):
            for name, value in block.items():
                take(name, value, section=section)

    for name, value in data.items():
        if name in _SECTIONS or name in _METADATA_KEYS:
            continue
        if isinstance(value, (int, float, str)):
            take(name, value)

    if (
        not attributes
        and not positions
        and not personality
        and current_ability is None
        and potential_ability is None
    ):
        raise PlayerWriteError("no recognisable attributes found in file")

    return attributes, positions, personality, current_ability, potential_ability


def import_from_file(path: str) -> ImportedProfile:
    with open(path, encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as e:
            raise PlayerWriteError(f"invalid JSON: {e}") from None
    return parse_import(data)
