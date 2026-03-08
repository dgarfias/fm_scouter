"""
Club data structures and reader for FM24.

Reads club objects from the FM24 database table at dbtRoot + 0x10,
extracting name, short name, nation, and reputation (from team objects).
"""

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .memory import MemoryReader

__all__ = ["Club", "ClubReader", "enrich_clubs_with_players"]

_CLUB_DB_OFFSET = 0x10
_TEAM_DB_OFFSET = 0x98
_TABLE_CONTAINER_OFFSET = 0x80
_CLUB_READ_SIZE = 0x170

_OFF_NAME = 0xC0
_OFF_SHORT_NAME = 0xC8
_OFF_NATION = 0xD8
_OFF_NATION_NAME = 0x18

_TEAM_READ_SIZE = 0xB0
_TEAM_OFF_CLUB = 0x30
_TEAM_OFF_REPUTATION = 0xA8


@dataclass(slots=True)
class Club:
    address: int = 0
    uid: int = 0
    name: str = ""
    short_name: str = ""
    nation: str = ""
    reputation: int = 0  # 0-10000
    squad_size: int = 0
    avg_ca: float = 0.0
    avg_age: float = 0.0
    best_ca: int = 0
    club_ability: float = 0.0
    club_potential: float = 0.0
    league: str = ""
    continent: str = ""

    @property
    def display_name(self) -> str:
        return self.short_name or self.name or "Unknown"


def enrich_clubs_with_players(clubs: list["Club"], players: list, game_year: int = 2024):
    """Attach squad stats to clubs using player data.

    Club ability = avg CA of top 25 players currently at the club
                   (includes loaned-in, excludes loaned-out).
    Club potential = avg effective rating of top 25 players owned by the club
                     (includes loaned-out, excludes loaned-in).
    Always divide by 25 so thin squads are penalized.
    """
    from collections import defaultdict

    current_at: dict[str, list] = defaultdict(list)
    owned_by: dict[str, list] = defaultdict(list)

    for p in players:
        if not p.club or p.current_ability <= 0:
            continue
        current_at[p.club].append(p)
        if getattr(p, "on_loan", False) and getattr(p, "parent_club", ""):
            owned_by[p.parent_club].append(p)
        else:
            owned_by[p.club].append(p)

    club_by_name: dict[str, "Club"] = {}
    for c in clubs:
        club_by_name[c.name] = c

    for club_name, c in club_by_name.items():
        at_club = current_at.get(club_name, [])
        owned = owned_by.get(club_name, [])

        ability_cas = sorted(
            [p.current_ability for p in at_club],
            reverse=True,
        )[:25]

        potential_vals = []
        for p in owned:
            age = (game_year - p.birth_year) if p.birth_year and p.birth_year > 1900 else 30
            if age < 24 and p.potential_ability > p.current_ability:
                potential_vals.append(p.potential_ability)
            else:
                potential_vals.append(p.current_ability)
        potential_vals.sort(reverse=True)
        top_pot = potential_vals[:25]

        all_cas = [p.current_ability for p in at_club]
        ages = [
            game_year - p.birth_year
            for p in at_club
            if p.birth_year and p.birth_year > 1900
        ]

        c.squad_size = len(at_club)
        c.avg_ca = sum(all_cas) / len(all_cas) if all_cas else 0.0
        c.best_ca = max(all_cas) if all_cas else 0
        c.club_ability = sum(ability_cas) / 25
        c.club_potential = sum(top_pot) / 25
        c.avg_age = sum(ages) / len(ages) if ages else 0.0
        if at_club:
            c.league = at_club[0].league or ""
            c.continent = getattr(at_club[0], "league_continent", "") or ""


class ClubReader:
    def __init__(self, reader: "MemoryReader", dbt_root: int):
        self.reader = reader
        self.dbt_root = dbt_root
        self._nation_cache: dict[int, str] = {}

    def read_all_clubs(self) -> list[Club]:
        club_ptrs = self._read_club_table()
        if not club_ptrs:
            return []

        reader = self.reader
        nation_cache = self._nation_cache
        clubs: list[Club] = []

        if reader.has_batch_read:
            bulk = reader.batch_read_fixed(club_ptrs, _CLUB_READ_SIZE)
            for ptr in club_ptrs:
                data = bulk.get(ptr)
                if data is None:
                    continue
                club = self._parse_club(ptr, data, nation_cache)
                if club is not None:
                    clubs.append(club)
        else:
            read_bytes = reader.read_bytes
            for ptr in club_ptrs:
                data = read_bytes(ptr, _CLUB_READ_SIZE)
                if data is None or len(data) < _CLUB_READ_SIZE:
                    continue
                club = self._parse_club(ptr, data, nation_cache)
                if club is not None:
                    clubs.append(club)

        team_reps = self._read_team_reputations()
        if team_reps:
            for c in clubs:
                rep = team_reps.get(c.address, 0)
                if rep > 0:
                    c.reputation = rep

        return clubs

    def _read_team_reputations(self) -> dict[int, int]:
        """Read team table and return {club_ptr: max_reputation}."""
        reader = self.reader
        team_db = reader.read_pointer(self.dbt_root + _TEAM_DB_OFFSET)
        if not team_db:
            return {}
        table_ptr = reader.read_pointer(team_db + _TABLE_CONTAINER_OFFSET)
        if not table_ptr:
            return {}
        start = reader.read_pointer(table_ptr)
        end = reader.read_pointer(table_ptr + 8)
        if not start or not end or end <= start:
            return {}

        count = (end - start) // 8
        if count > 200_000:
            return {}

        raw = reader.read_bytes(start, count * 8)
        if raw is None or len(raw) < count * 8:
            return {}

        team_ptrs = []
        for i in range(count):
            val = struct.unpack_from("<Q", raw, i * 8)[0]
            if val != 0:
                team_ptrs.append(val)

        club_rep: dict[int, int] = {}
        if reader.has_batch_read:
            bulk = reader.batch_read_fixed(team_ptrs, _TEAM_READ_SIZE)
            for tp in team_ptrs:
                tdata = bulk.get(tp)
                if tdata is None or len(tdata) < _TEAM_READ_SIZE:
                    continue
                club_ptr = struct.unpack_from("<Q", tdata, _TEAM_OFF_CLUB)[0]
                rep = struct.unpack_from("<H", tdata, _TEAM_OFF_REPUTATION)[0]
                if club_ptr and 0 < rep <= 10_000:
                    if rep > club_rep.get(club_ptr, 0):
                        club_rep[club_ptr] = rep
        else:
            for tp in team_ptrs:
                tdata = reader.read_bytes(tp, _TEAM_READ_SIZE)
                if tdata is None or len(tdata) < _TEAM_READ_SIZE:
                    continue
                club_ptr = struct.unpack_from("<Q", tdata, _TEAM_OFF_CLUB)[0]
                rep = struct.unpack_from("<H", tdata, _TEAM_OFF_REPUTATION)[0]
                if club_ptr and 0 < rep <= 10_000:
                    if rep > club_rep.get(club_ptr, 0):
                        club_rep[club_ptr] = rep

        return club_rep

    def _read_club_table(self) -> list[int]:
        reader = self.reader
        club_db = reader.read_pointer(self.dbt_root + _CLUB_DB_OFFSET)
        if not club_db:
            return []
        table_ptr = reader.read_pointer(club_db + _TABLE_CONTAINER_OFFSET)
        if not table_ptr:
            return []
        start = reader.read_pointer(table_ptr)
        end = reader.read_pointer(table_ptr + 8)
        if not start or not end or end <= start:
            return []

        count = (end - start) // 8
        if count > 200_000:
            return []

        raw = reader.read_bytes(start, count * 8)
        if raw is None or len(raw) < count * 8:
            return []

        ptrs: list[int] = []
        for i in range(count):
            val = struct.unpack_from("<Q", raw, i * 8)[0]
            if val != 0:
                ptrs.append(val)
        return ptrs

    def _parse_club(self, ptr: int, data: bytes,
                    nation_cache: dict[int, str]) -> Club | None:
        reader = self.reader
        read_string = reader.read_string

        name_entry = struct.unpack_from("<Q", data, _OFF_NAME)[0]
        name = ""
        if name_entry:
            s = read_string(name_entry + 4, max_len=96)
            if s and s.isprintable():
                name = s

        short_name_entry = struct.unpack_from("<Q", data, _OFF_SHORT_NAME)[0]
        short_name = ""
        if short_name_entry:
            s = read_string(short_name_entry + 4, max_len=96)
            if s and s.isprintable():
                short_name = s

        if not name and not short_name:
            return None

        nation_ptr = struct.unpack_from("<Q", data, _OFF_NATION)[0]
        nation = ""
        if nation_ptr:
            cached = nation_cache.get(nation_ptr)
            if cached is not None:
                nation = cached
            else:
                nation_name_entry = reader.read_pointer(nation_ptr + _OFF_NATION_NAME)
                if nation_name_entry:
                    s = read_string(nation_name_entry + 4, max_len=64)
                    if s and s.isprintable():
                        nation = s
                nation_cache[nation_ptr] = nation

        return Club(
            address=ptr,
            name=name,
            short_name=short_name,
            nation=nation,
        )
