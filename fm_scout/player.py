"""Player data model and memory reader for FM24.

Reads player (plao) and person (pero) data from the FM24 process memory
using pure-Python parsing and batched I/O.
"""

import struct
import logging
from dataclasses import dataclass, field
from typing import Optional

from .offsets import (
    ATTR_OFFSETS, STRUCT_OFFSETS, POSITION_NAMES, PERSONALITY_NAMES,
    ATTRIBUTE_BYTE_OFFSETS, StructOffsets, AttributeOffsets,
)

PLAYER_TRAIT_MAP: list[tuple[int, int, str]] = [
    (0, 0, "Runs With Ball Down Left"),
    (0, 1, "Runs With Ball Down Right"),
    (0, 2, "Runs With Ball Down Center"),
    (0, 3, "Gets Into Opposition Area"),
    (0, 4, "Moves Into Channels"),
    (0, 5, "Gets Forward Whenever Possible"),
    (0, 6, "Plays Short Simple Passes"),
    (0, 7, "Tries Killer Balls Often"),
    (1, 0, "Shoots From Distance"),
    (1, 1, "Shoots With Power"),
    (1, 2, "Places Shots"),
    (1, 3, "Curls Ball"),
    (1, 4, "Likes To Round Keeper"),
    (1, 5, "Likes To Break Offside Trap"),
    (1, 6, "Uses Outside Of Foot"),
    (1, 7, "Marks Opponent Tightly"),
    (2, 0, "Winds Up Opponents"),
    (2, 1, "Argues With Officials"),
    (2, 2, "Plays With Back To Goal"),
    (2, 3, "Comes Deep To Get Ball"),
    (2, 4, "Plays One-Twos"),
    (2, 5, "Likes To Lob Keeper"),
    (2, 6, "Dictates Tempo"),
    (2, 7, "Attempts Overhead Kicks"),
    (3, 0, "Looks For Pass Rather Than Attempting To Score"),
    (3, 1, "Plays No Through Balls"),
    (3, 2, "Stops Play"),
    (3, 3, "Knocks Ball Past Opponent"),
    (3, 4, "Moves Ball To Right Foot Before Dribble"),
    (3, 5, "Moves Ball To Left Foot Before Dribble"),
    (3, 6, "Dwells On Ball"),
    (3, 7, "Arrives Late In Opponents' Area"),
    (4, 0, "Tries To Play Way Out Of Trouble"),
    (4, 1, "Stays Back At All Times"),
    (4, 2, "Avoids Using Weaker Foot"),
    (4, 3, "Tries Tricks"),
    (4, 4, "Tries Long Range Free Kicks"),
    (4, 5, "Dives Into Tackles"),
    (5, 0, "Hugs Line"),
    (5, 6, "Likes To Beat Opponent Repeatedly"),
    (6, 0, "Shows Onto Weaker Foot"),
    (7, 0, "Refrains From Taking Long Shots"),
]
from .memory import MemoryReader

logger = logging.getLogger('fm_scout')


_ALL_ATTR_NAMES: tuple[str, ...] = (
    AttributeOffsets.TECHNICAL_FIELDS
    + AttributeOffsets.MENTAL_FIELDS
    + AttributeOffsets.PHYSICAL_FIELDS
    + AttributeOffsets.GOALKEEPER_FIELDS
    + AttributeOffsets.HIDDEN_FIELDS
)


# ====================================================================== #
#  Data models                                                            #
# ====================================================================== #

@dataclass(slots=True)
class PlayerAttributes:
    """All 54 player attributes (1-20 display scale)."""

    # Technical (14)
    crossing: int = 0
    dribbling: int = 0
    finishing: int = 0
    heading: int = 0
    long_shots: int = 0
    marking: int = 0
    passing: int = 0
    penalty_taking: int = 0
    tackling: int = 0
    first_touch: int = 0
    technique: int = 0
    corners: int = 0
    long_throws: int = 0
    free_kick_taking: int = 0

    # Mental (14)
    off_the_ball: int = 0
    vision: int = 0
    anticipation: int = 0
    decisions: int = 0
    positioning: int = 0
    flair: int = 0
    teamwork: int = 0
    work_rate: int = 0
    leadership: int = 0
    bravery: int = 0
    aggression: int = 0
    determination: int = 0
    composure: int = 0
    concentration: int = 0

    # Physical (8)
    acceleration: int = 0
    strength: int = 0
    stamina: int = 0
    pace: int = 0
    jumping_reach: int = 0
    balance: int = 0
    agility: int = 0
    natural_fitness: int = 0

    # Goalkeeper (11)
    handling: int = 0
    aerial_reach: int = 0
    command_of_area: int = 0
    communication: int = 0
    kicking: int = 0
    throwing: int = 0
    one_on_ones: int = 0
    reflexes: int = 0
    eccentricity: int = 0
    rushing_out: int = 0
    punching: int = 0

    # Hidden (7)
    left_foot: int = 0
    right_foot: int = 0
    dirtiness: int = 0
    consistency: int = 0
    important_matches: int = 0
    injury_proneness: int = 0
    versatility: int = 0

    def get(self, name: str, default: int = 0) -> int:
        return getattr(self, name, default)

    def to_dict(self) -> dict:
        return {name: getattr(self, name, 0) for name in _ALL_ATTR_NAMES}


@dataclass(slots=True)
class Player:
    """A single player record with identity, ability, contract, and attributes."""

    address: int = 0
    plao_address: int = 0

    first_name: str = ""
    last_name: str = ""
    common_name: str = ""

    uid: int = 0
    current_ability: int = 0
    potential_ability: int = 0
    birth_year: int = 0
    birth_day_of_year: int = 0
    current_reputation: int = 0
    world_reputation: int = 0
    nationality: str = ""
    nationalities: list[str] = field(default_factory=list)

    club: str = ""
    club_address: int = 0
    league: str = ""
    league_nation: str = ""
    league_continent: str = ""
    league_type: int = -1
    on_loan: bool = False
    parent_club: str = ""
    parent_club_address: int = 0

    height: int = 0
    weight: int = 0
    wage: int = 0
    value: int = 0
    transfer_value: int = 0
    transfer_listed: bool = False
    loan_listed: bool = False
    listed_reason: str = ""

    contract_expiry: int = 0
    contract_transfer_opts: int = 0
    contract_option_years: int = 0

    positions: dict[str, int] = field(default_factory=dict)
    attributes: PlayerAttributes = field(default_factory=PlayerAttributes)
    personality: dict[str, int] = field(default_factory=dict)
    traits: list[str] = field(default_factory=list)

    vtable: int = 0
    is_player: bool = True

    @property
    def display_name(self) -> str:
        if self.common_name:
            return self.common_name
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def nationality_display(self) -> str:
        if self.nationalities:
            return ", ".join(self.nationalities)
        return self.nationality

    @property
    def best_position(self) -> str:
        if not self.positions:
            return ""
        return max(self.positions, key=self.positions.get)

    @property
    def position_str(self) -> str:
        good = [pos for pos, rating in self.positions.items() if rating >= 15]
        if good:
            return ", ".join(good)
        return self.best_position

    @property
    def reputation(self) -> int:
        """Compatibility alias for legacy UI code."""
        return self.current_reputation

    @property
    def birth_day(self) -> int:
        """Compatibility alias for legacy UI code."""
        return self.birth_day_of_year

    def __getattr__(self, name: str):
        """Expose nested attribute/personality values as legacy flat fields."""
        if name in _ALL_ATTR_NAMES:
            return self.attributes.get(name)
        if name.startswith("pers_"):
            key = name[5:].replace("_", " ").title()
            return self.personality.get(key, 0)
        raise AttributeError(name)

    def to_dict(self) -> dict:
        return {
            'uid': self.uid,
            'name': self.display_name,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'common_name': self.common_name,
            'ca': self.current_ability,
            'pa': self.potential_ability,
            'club': self.club,
            'club_address': self.club_address,
            'league': self.league,
            'nationality': self.nationality,
            'nationalities': list(self.nationalities),
            'birth_year': self.birth_year,
            'birth_day': self.birth_day_of_year,
            'current_reputation': self.current_reputation,
            'world_reputation': self.world_reputation,
            'height': self.height,
            'weight': self.weight,
            'wage': self.wage,
            'value': self.value,
            'positions': dict(self.positions),
            'best_position': self.best_position,
            'on_loan': self.on_loan,
            'parent_club': self.parent_club,
            'parent_club_address': self.parent_club_address,
            'transfer_listed': self.transfer_listed,
            'loan_listed': self.loan_listed,
            'contract_expiry': self.contract_expiry,
            **self.attributes.to_dict(),
        }


# ====================================================================== #
#  Player reader                                                          #
# ====================================================================== #

class PlayerReader:
    """Reads player data from FM24 process memory.

    Uses pure-Python parsing with multi-phase batch I/O for efficient
    bulk reads of 100k+ players.
    """

    PLAYER_VTABLES: set[int] = set()

    _CONTRACT_READ_SIZE = 0x60
    _NAME_BUF_SIZE = 96
    _NATION_NAME_BUF_SIZE = 64
    # Nationality list entries live in the leading qwords of the list node.
    # Scanning deeper pulls unrelated linked metadata (false positives).
    _NATION_LIST_SCAN_SIZE = 0x80
    _KNOWN_CONTINENTS = {
        "Europe", "Africa", "Asia",
        "South America", "North America", "Oceania",
    }

    def __init__(self, reader: MemoryReader, struct_offsets: StructOffsets,
                 attr_offsets: AttributeOffsets = ATTR_OFFSETS):
        self.reader = reader
        self.so = struct_offsets
        self.ao = attr_offsets

        self._club_cache: dict[int, tuple] = {}
        self._name_cache: dict[int, str] = {}
        self._nation_cache: dict[int, str] = {}

        self._name_fields = (
            struct_offsets.pfna,
            struct_offsets.psna,
            struct_offsets.pcna,
        )
        self._personality_names_8 = PERSONALITY_NAMES[:8]
        self._position_names = POSITION_NAMES

        # Explicit per-attribute byte offsets inside plao.Patr.
        self._attr_byte_offsets = tuple(
            ATTRIBUTE_BYTE_OFFSETS[name] for name in _ALL_ATTR_NAMES
        )

        # Combined read geometry:
        #   read_start = plao_base + pwes
        #   pero_start = plao_base + player_offset
        #   pero_in_combined = player_offset - pwes
        #   combined_size covers pero up through ploan_contract (0xD0) + 8
        self._pero_in_combined = struct_offsets.player_offset - struct_offsets.pwes
        self._combined_size = self._pero_in_combined + 0xD8

    # ------------------------------------------------------------------ #
    #  Single-player read                                                 #
    # ------------------------------------------------------------------ #

    def read_player(self, person_ptr: int) -> Optional[Player]:
        """Read a single player from memory by person pointer.

        Used for individual player lookups and refresh operations.
        """
        reader = self.reader
        so = self.so

        vtable = reader.read_pointer(person_ptr)
        if not vtable:
            return None

        type_offset = so.player_offset
        if self.PLAYER_VTABLES and vtable not in self.PLAYER_VTABLES:
            return None
        type_info = reader.read_pointer(vtable - 8)
        if not type_info:
            return None
        offset_val = reader.read_uint32(type_info + 4)
        if offset_val is None or offset_val != type_offset:
            return None

        read_start = person_ptr - type_offset + so.pwes
        combined = reader.read_bytes(read_start, self._combined_size)
        if combined is None or len(combined) < self._combined_size:
            return None

        player = Player(
            address=person_ptr,
            plao_address=person_ptr - type_offset,
            vtable=vtable,
        )

        result = self._parse_combined_py(combined, player)
        if result is None:
            return None
        contract_ptr, loan_ptr, fna_ptr, sna_ptr, cna_ptr, nti_ptr, nation_list_root_ptr = result

        player.first_name = self._resolve_name(fna_ptr)
        player.last_name = self._resolve_name(sna_ptr)
        player.common_name = self._resolve_name(cna_ptr)
        primary_nation = self._resolve_nation(nti_ptr)
        player.nationality = primary_nation
        nations: list[str] = []
        if primary_nation:
            nations.append(primary_nation)
        for n_ptr in self._resolve_nation_ptrs_from_root(nation_list_root_ptr):
            n_name = self._resolve_nation(n_ptr)
            if not n_name:
                continue
            if n_name not in nations:
                nations.append(n_name)
        player.nationalities = nations or ([primary_nation] if primary_nation else [])

        if contract_ptr:
            self._read_contract(player, contract_ptr)

        if loan_ptr:
            self._resolve_loan(player, loan_ptr)

        self._read_traits(player)

        return player

    # ------------------------------------------------------------------ #
    #  Batch player read (multi-phase)                                    #
    # ------------------------------------------------------------------ #

    def read_all_players(self, person_ptrs: list[int]) -> list[Player]:
        """Read all players using batched I/O with five processing phases.

        Phase 1: Batch vtable prefilter -- identify players vs non-players.
        Phase 2: Batch read combined pero+plao memory regions.
        Phase 3: Parse combined data + batch-resolve names/nationality.
        Phase 4: Batch read contract data.
        Phase 5: Parse contracts, resolve clubs, detect loans.
        """
        reader = self.reader
        so = self.so
        combined_size = self._combined_size
        player_vtables = self.PLAYER_VTABLES

        if not person_ptrs:
            return []

        # If vtable discovery is incomplete, validate each candidate individually.
        if not player_vtables:
            players: list[Player] = []
            for ptr in person_ptrs:
                p = self.read_player(ptr)
                if p is not None:
                    players.append(p)
            logger.info(
                "read_all_players: %d players from %d entries (fallback mode)",
                len(players), len(person_ptrs),
            )
            return players

        # ---- Phase 1: batch vtable prefilter ----

        vtable_results = reader.batch_read_u64(person_ptrs)

        player_offset = so.player_offset
        vtable_is_player: dict[int, bool] = {}
        candidates: list[tuple[int, int, int]] = []
        read_addrs: list[int] = []

        for ptr, vtable in vtable_results:
            if vtable in player_vtables:
                is_player = vtable_is_player.get(vtable)
                if is_player is None:
                    type_info = reader.read_pointer(vtable - 8)
                    offset_val = (
                        reader.read_uint32(type_info + 4) if type_info else None
                    )
                    is_player = offset_val == player_offset
                    vtable_is_player[vtable] = is_player
                if not is_player:
                    continue
                candidates.append((ptr, vtable, player_offset))
                read_addrs.append(ptr - player_offset + so.pwes)

        logger.debug(
            "Phase 1: %d/%d candidates are players",
            len(candidates), len(vtable_results),
        )
        if not candidates:
            return []

        # ---- Phase 2: batch read combined pero+plao ----

        combined_data = reader.batch_read_fixed(read_addrs, combined_size)
        logger.debug(
            "Phase 2: got %d/%d combined buffers (%d bytes each)",
            len(combined_data), len(read_addrs), combined_size,
        )

        # ---- Phase 3: parse pero+plao + batch resolve names ----

        # pending entries: (Player, contract_ptr, loan_ptr)
        pending: list[tuple[Player, int, int]] = []
        name_ptrs_needed: set[int] = set()
        nation_ptrs_needed: set[int] = set()
        name_cache = self._name_cache
        nation_cache = self._nation_cache

        parsed: list[tuple] = []

        for i, (ptr, vtable, type_offset) in enumerate(candidates):
            combined = combined_data.get(read_addrs[i])
            if combined is None:
                continue

            player = Player(
                address=ptr,
                plao_address=ptr - type_offset,
                vtable=vtable,
            )
            result = self._parse_combined_py(combined, player)
            if result is None:
                continue

            contract_ptr, loan_ptr, fna_ptr, sna_ptr, cna_ptr, nti_ptr, nation_list_root_ptr = result
            for p in (fna_ptr, sna_ptr, cna_ptr):
                if p and p not in name_cache:
                    name_ptrs_needed.add(p)
            if nti_ptr and nti_ptr not in nation_cache:
                nation_ptrs_needed.add(nti_ptr)

            parsed.append((
                player, contract_ptr, loan_ptr,
                fna_ptr, sna_ptr, cna_ptr, nti_ptr, nation_list_root_ptr,
            ))

        # Batch resolve all names and nationalities
        if name_ptrs_needed:
            self._batch_resolve_names(name_ptrs_needed)
        if nation_ptrs_needed:
            self._batch_resolve_nations(nation_ptrs_needed)

        # Batch-resolve extra nationalities from nation-list roots.
        sec_ptrs_by_person: dict[int, list[int]] = {}
        sec_ptrs_needed: set[int] = set()
        if parsed:
            root_child_addr_set: set[int] = set()
            person_root: dict[int, int] = {}
            for player, _, _, _, _, _, _, root_ptr in parsed:
                person_root[player.address] = root_ptr or 0
                if root_ptr:
                    root_child_addr_set.add(root_ptr)

            root_child_map = dict(reader.batch_read_u64(list(root_child_addr_set))) if root_child_addr_set else {}
            child_ptrs: list[int] = []
            for root_ptr in person_root.values():
                child = root_child_map.get(root_ptr, 0)
                if child:
                    child_ptrs.append(child)

            child_blobs = reader.batch_read_fixed(
                list(set(child_ptrs)),
                self._NATION_LIST_SCAN_SIZE,
            ) if child_ptrs else {}

            for player, _, _, _, _, _, _, root_ptr in parsed:
                child = root_child_map.get(root_ptr, 0) if root_ptr else 0
                if not child:
                    continue
                blob = child_blobs.get(child)
                if not blob:
                    continue
                ptrs = self._extract_nation_ptrs_from_blob(blob)
                if ptrs:
                    sec_ptrs_by_person[player.address] = ptrs
                    for ptr in ptrs:
                        if ptr not in nation_cache:
                            sec_ptrs_needed.add(ptr)

        if sec_ptrs_needed:
            self._batch_resolve_nations(sec_ptrs_needed)

        # Assign resolved names and build pending list
        for player, contract_ptr, loan_ptr, fna, sna, cna, nti, _root in parsed:
            player.first_name = name_cache.get(fna, "")
            player.last_name = name_cache.get(sna, "")
            player.common_name = name_cache.get(cna, "")
            primary_nation = nation_cache.get(nti, "")
            player.nationality = primary_nation
            nations: list[str] = []
            if primary_nation:
                nations.append(primary_nation)
            for n_ptr in sec_ptrs_by_person.get(player.address, []):
                n_name = nation_cache.get(n_ptr, "")
                if not n_name:
                    continue
                if n_name not in nations:
                    nations.append(n_name)
            player.nationalities = nations or ([primary_nation] if primary_nation else [])
            pending.append((player, contract_ptr, loan_ptr))

        logger.debug("Phase 3: %d players parsed", len(pending))
        if not pending:
            return []

        # ---- Phase 4: batch read contracts ----

        contract_addrs: list[int] = []
        for _, contract_ptr, _ in pending:
            if contract_ptr:
                contract_addrs.append(contract_ptr)

        contract_data: dict[int, bytes] = {}
        if contract_addrs:
            contract_data = reader.batch_read_fixed(
                contract_addrs, self._CONTRACT_READ_SIZE,
            )
        logger.debug(
            "Phase 4: read %d/%d contracts",
            len(contract_data), len(contract_addrs),
        )

        # ---- Phase 5: parse contracts, resolve clubs, handle loans ----

        players: list[Player] = []

        for player, contract_ptr, loan_ptr in pending:
            if contract_ptr:
                cdata = contract_data.get(contract_ptr)
                if cdata:
                    team_ptr = self._parse_contract_data(player, cdata)

                    if team_ptr:
                        self._resolve_club_chain(player, team_ptr)

            if loan_ptr:
                self._resolve_loan(player, loan_ptr)

            self._read_traits(player)

            players.append(player)

        logger.info(
            "read_all_players: %d players from %d entries",
            len(players), len(person_ptrs),
        )
        return players

    # ------------------------------------------------------------------ #
    #  Python fallback parsing                                            #
    # ------------------------------------------------------------------ #

    def _parse_combined_py(
        self, combined: bytes, player: Player,
    ) -> Optional[tuple[int, int, int, int, int, int, int]]:
        """Parse combined pero+plao bytes in pure Python.

        Populates scalar fields on *player* and returns a tuple of
        ``(contract_ptr, loan_ptr, fna_ptr, sna_ptr, cna_ptr, nti_ptr, nation_list_root_ptr)``
        for deferred name/contract resolution, or ``None`` on failure.
        """
        so = self.so
        pwes = so.pwes
        pero = self._pero_in_combined
        scale = so.attr_scale

        # -- plao fields (offsets relative to combined start = plao_base + pwes) --

        weight = struct.unpack_from('<h', combined, 0)[0]
        height = struct.unpack_from('<h', combined, so.phes - pwes)[0]
        crp = struct.unpack_from('<H', combined, so.pcrp - pwes)[0]
        wrp = struct.unpack_from('<H', combined, so.pwrp - pwes)[0]
        ca = struct.unpack_from('<h', combined, so.pcab - pwes)[0]
        pa = struct.unpack_from('<h', combined, so.ppab - pwes)[0]

        player.weight = weight if 30 <= weight <= 150 else 0
        player.height = height if 100 <= height <= 230 else 0
        player.current_reputation = crp
        player.world_reputation = wrp
        player.current_ability = self._normalize_ability(ca)
        player.potential_ability = self._normalize_ability(pa)

        # Positions (already 1-20 scale in memory)
        pos_off = so.ppos - pwes
        positions: dict[str, int] = {}
        for i, name in enumerate(self._position_names):
            val = combined[pos_off + i]
            if val > 0:
                positions[name] = val
        player.positions = positions

        # Attributes (raw 0-100, scale down to 1-20)
        attr_off = so.patr - pwes
        half = scale >> 1
        attrs = PlayerAttributes()
        for i, name in enumerate(_ALL_ATTR_NAMES):
            raw = combined[attr_off + self._attr_byte_offsets[i]]
            setattr(attrs, name, (raw + half) // scale if raw > 0 else 0)
        player.attributes = attrs

        # -- pero fields (pero_in_combined bytes into the combined buffer) --

        uid = struct.unpack_from('<I', combined, pero + so.duni)[0]
        birth_day = struct.unpack_from('<H', combined, pero + so.pdob_day)[0]
        birth_year = struct.unpack_from('<H', combined, pero + so.pdob_year)[0]

        player.uid = uid
        player.birth_day_of_year = birth_day if 1 <= birth_day <= 366 else 0
        player.birth_year = birth_year if 1900 <= birth_year <= 2020 else 0

        # Personality traits (8 bytes at pada)
        pers_off = pero + so.pada
        personality: dict[str, int] = {}
        for i, name in enumerate(self._personality_names_8):
            val = combined[pers_off + i]
            if val > 0:
                personality[name] = val
        player.personality = personality

        # Name and nationality pointers
        fna_ptr = struct.unpack_from('<Q', combined, pero + so.pfna)[0]
        sna_ptr = struct.unpack_from('<Q', combined, pero + so.psna)[0]
        cna_ptr = struct.unpack_from('<Q', combined, pero + so.pcna)[0]
        nti_ptr = struct.unpack_from('<Q', combined, pero + so.pnti)[0]
        nation_list_root_ptr = struct.unpack_from('<Q', combined, pero + so.nation_list_root)[0]

        # Contract pointer
        contract_ptr = struct.unpack_from('<Q', combined, pero + so.pcontract)[0]

        # Loan contract pointer (may extend past the minimal pero region)
        loan_off = pero + so.ploan_contract
        loan_ptr = 0
        if loan_off + 8 <= len(combined):
            loan_ptr = struct.unpack_from('<Q', combined, loan_off)[0]

        return (
            contract_ptr, loan_ptr, fna_ptr, sna_ptr, cna_ptr, nti_ptr,
            nation_list_root_ptr,
        )

    @staticmethod
    def _normalize_ability(val: int) -> int:
        """Normalize FM ability values across known storage scales."""
        if val <= 0:
            return 0
        # Some builds expose CA/PA scaled by 100 (e.g. 7500 -> 75).
        if val > 250:
            val = (val + 50) // 100
        if val > 200:
            return 200
        return val

    # ------------------------------------------------------------------ #
    #  Batch name / nationality resolution                                #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_string_buf(buf: bytes) -> str:
        """Decode a null-terminated string from a raw memory buffer."""
        if not buf:
            return ""
        null = buf.find(b'\x00')
        if null >= 0:
            buf = buf[:null]
        if not buf:
            return ""
        try:
            s = buf.decode('utf-8')
        except UnicodeDecodeError:
            s = buf.decode('latin-1')
        return s if s.isprintable() else ""

    def _batch_resolve_names(self, ptrs: set[int]):
        """Batch-read name entry strings and populate the name cache.

        Each *ptr* is a name-entry pointer; the actual UTF-8 string
        starts at ``ptr + 4`` (after a 4-byte length/hash header).
        """
        if not ptrs:
            return

        reader = self.reader
        cache = self._name_cache
        buf_size = self._NAME_BUF_SIZE

        # Some builds store a wrapper node at name_ptr where [0] points to
        # the actual name entry; others store the entry directly.
        # Read both forms in batch and prefer the indirect form when present.
        direct_addrs = [p + 4 for p in ptrs]
        direct_bufs = reader.batch_read_fixed(direct_addrs, buf_size)

        head_ptrs = dict(reader.batch_read_u64(list(ptrs)))
        indirect_addrs = [q + 4 for q in head_ptrs.values() if q]
        indirect_bufs = reader.batch_read_fixed(indirect_addrs, buf_size) if indirect_addrs else {}

        for ptr in ptrs:
            name = ""
            head = head_ptrs.get(ptr, 0)
            if head:
                raw = indirect_bufs.get(head + 4)
                name = self._parse_string_buf(raw) if raw else ""
            if not name:
                raw = direct_bufs.get(ptr + 4)
                name = self._parse_string_buf(raw) if raw else ""
            cache[ptr] = name

    def _batch_resolve_nations(self, ptrs: set[int]):
        """Batch-read nationality objects and populate the nation cache.

        Resolves country names from nation objects and validates they are
        true nations by requiring a valid continent chain.
        """
        if not ptrs:
            return

        reader = self.reader
        cache = self._nation_cache
        so = self.so

        # Phase A: batch read nation -> (name_entry, continent_ptr)
        nation_addrs = [p + so.nation_name for p in ptrs]
        entry_bufs = reader.batch_read_fixed(nation_addrs, 8)
        cont_addrs = [p + so.nation_continent for p in ptrs]
        cont_ptr_bufs = reader.batch_read_fixed(cont_addrs, 8)

        name_entry_map: dict[int, int] = {}
        cont_ptr_map: dict[int, int] = {}
        nation_string_addrs: list[int] = []

        for ptr in ptrs:
            nbuf = entry_bufs.get(ptr + so.nation_name)
            cbuf = cont_ptr_bufs.get(ptr + so.nation_continent)
            name_entry = struct.unpack('<Q', nbuf)[0] if nbuf and len(nbuf) == 8 else 0
            cont_ptr = struct.unpack('<Q', cbuf)[0] if cbuf and len(cbuf) == 8 else 0
            if name_entry and cont_ptr:
                name_entry_map[ptr] = name_entry
                cont_ptr_map[ptr] = cont_ptr
                nation_string_addrs.append(name_entry + 4)
            else:
                cache[ptr] = ""

        if not nation_string_addrs:
            return

        # Phase B: decode nation names.
        nation_string_bufs = reader.batch_read_fixed(
            nation_string_addrs, self._NATION_NAME_BUF_SIZE,
        )
        head_ptrs = dict(reader.batch_read_u64(list(name_entry_map.values())))
        indirect_addrs = [q + 4 for q in head_ptrs.values() if q]
        indirect_bufs = (
            reader.batch_read_fixed(indirect_addrs, self._NATION_NAME_BUF_SIZE)
            if indirect_addrs
            else {}
        )
        nation_name_by_entry: dict[int, str] = {}
        for name_entry in set(name_entry_map.values()):
            nation = ""
            head = head_ptrs.get(name_entry, 0)
            if head:
                raw = indirect_bufs.get(head + 4)
                nation = self._parse_string_buf(raw) if raw else ""
            if not nation:
                raw = nation_string_bufs.get(name_entry + 4)
                nation = self._parse_string_buf(raw) if raw else ""
            nation_name_by_entry[name_entry] = nation

        # Phase C: decode continent names and validate nation pointers.
        unique_cont_ptrs = set(cont_ptr_map.values())
        cont_name_entry_addrs = [cp + so.continent_name for cp in unique_cont_ptrs]
        cont_entry_bufs = reader.batch_read_fixed(cont_name_entry_addrs, 8)
        cont_name_entry_by_ptr: dict[int, int] = {}
        cont_string_addrs: list[int] = []
        for cp in unique_cont_ptrs:
            buf = cont_entry_bufs.get(cp + so.continent_name)
            entry = struct.unpack('<Q', buf)[0] if buf and len(buf) == 8 else 0
            if entry:
                cont_name_entry_by_ptr[cp] = entry
                cont_string_addrs.append(entry + 4)

        cont_string_bufs = reader.batch_read_fixed(
            cont_string_addrs, self._NATION_NAME_BUF_SIZE,
        ) if cont_string_addrs else {}
        cont_head_ptrs = dict(
            reader.batch_read_u64(list(cont_name_entry_by_ptr.values()))
        ) if cont_name_entry_by_ptr else {}
        cont_indirect_addrs = [q + 4 for q in cont_head_ptrs.values() if q]
        cont_indirect_bufs = (
            reader.batch_read_fixed(cont_indirect_addrs, self._NATION_NAME_BUF_SIZE)
            if cont_indirect_addrs
            else {}
        )
        continent_by_ptr: dict[int, str] = {}
        for cp, entry in cont_name_entry_by_ptr.items():
            cont = ""
            head = cont_head_ptrs.get(entry, 0)
            if head:
                raw = cont_indirect_bufs.get(head + 4)
                cont = self._parse_string_buf(raw) if raw else ""
            if not cont:
                raw = cont_string_bufs.get(entry + 4)
                cont = self._parse_string_buf(raw) if raw else ""
            continent_by_ptr[cp] = cont if cont in self._KNOWN_CONTINENTS else ""

        for ptr, name_entry in name_entry_map.items():
            if not continent_by_ptr.get(cont_ptr_map.get(ptr, 0), ""):
                cache[ptr] = ""
                continue
            cache[ptr] = nation_name_by_entry.get(name_entry, "")

    # ------------------------------------------------------------------ #
    #  Individual name / nationality resolution (for single-player path)  #
    # ------------------------------------------------------------------ #

    def _resolve_name(self, ptr: int) -> str:
        """Resolve a name-entry pointer to a display string."""
        if not ptr:
            return ""
        cached = self._name_cache.get(ptr)
        if cached is not None:
            return cached
        name = ""
        s = self.reader.read_string(ptr + 4, max_len=self._NAME_BUF_SIZE)
        if s and s.isprintable():
            name = s
        if not name:
            head = self.reader.read_pointer(ptr)
            if head:
                s2 = self.reader.read_string(head + 4, max_len=self._NAME_BUF_SIZE)
                if s2 and s2.isprintable():
                    name = s2
        self._name_cache[ptr] = name
        return name

    def _resolve_nation(self, ptr: int) -> str:
        """Resolve a nationality-object pointer to a country name string."""
        if not ptr:
            return ""
        cached = self._nation_cache.get(ptr)
        if cached is not None:
            return cached

        name_entry = self.reader.read_pointer(ptr + self.so.nation_name)
        cont_ptr = self.reader.read_pointer(ptr + self.so.nation_continent)
        nation = ""
        if name_entry and cont_ptr:
            s = self.reader.read_string(name_entry + 4, max_len=self._NATION_NAME_BUF_SIZE)
            if s and s.isprintable():
                nation = s
            if not nation:
                head = self.reader.read_pointer(name_entry)
                if head:
                    s2 = self.reader.read_string(head + 4, max_len=self._NATION_NAME_BUF_SIZE)
                    if s2 and s2.isprintable():
                        nation = s2
            # Strict validation: continent must resolve to a known continent.
            if nation:
                cont_name_entry = self.reader.read_pointer(cont_ptr + self.so.continent_name)
                continent = ""
                if cont_name_entry:
                    c = self.reader.read_string(
                        cont_name_entry + 4, max_len=self._NATION_NAME_BUF_SIZE,
                    )
                    if c and c.isprintable():
                        continent = c
                    if not continent:
                        chead = self.reader.read_pointer(cont_name_entry)
                        if chead:
                            c2 = self.reader.read_string(
                                chead + 4, max_len=self._NATION_NAME_BUF_SIZE,
                            )
                            if c2 and c2.isprintable():
                                continent = c2
                if continent not in self._KNOWN_CONTINENTS:
                    nation = ""
        self._nation_cache[ptr] = nation
        return nation

    @staticmethod
    def _extract_nation_ptrs_from_blob(blob: bytes) -> list[int]:
        counts: dict[int, int] = {}
        first_off: dict[int, int] = {}
        for off in range(0, len(blob) - 7, 8):
            ptr = struct.unpack_from('<Q', blob, off)[0]
            if not ptr or ptr < 0x10000 or ptr > 0x7FFFFFFFFFFF:
                continue
            counts[ptr] = counts.get(ptr, 0) + 1
            if ptr not in first_off:
                first_off[ptr] = off
        return sorted(
            counts.keys(),
            key=lambda p: (-counts[p], first_off[p]),
        )

    def _resolve_nation_ptrs_from_root(self, nation_list_root_ptr: int) -> list[int]:
        """Resolve additional nationality pointers from nation-list root."""
        if not nation_list_root_ptr:
            return []
        list_node_ptr = self.reader.read_pointer(nation_list_root_ptr)
        if not list_node_ptr:
            return []
        blob = self.reader.read_bytes(list_node_ptr, self._NATION_LIST_SCAN_SIZE)
        if not blob or len(blob) < 8:
            return []
        return self._extract_nation_ptrs_from_blob(blob)

    # ------------------------------------------------------------------ #
    #  Contract parsing                                                   #
    # ------------------------------------------------------------------ #

    def _read_contract(self, player: Player, contract_ptr: int):
        """Read and parse a single contract from memory."""
        cdata = self.reader.read_bytes(contract_ptr, self._CONTRACT_READ_SIZE)
        if cdata is None or len(cdata) < self._CONTRACT_READ_SIZE:
            return

        team_ptr = self._parse_contract_data(player, cdata)

        if team_ptr:
            self._resolve_club_chain(player, team_ptr)

    def _parse_contract_data(self, player: Player, cdata: bytes) -> int:
        """Parse contract data and return team_ptr."""
        so = self.so

        player.wage = struct.unpack_from('<I', cdata, so.contract_wage)[0]

        expiry_raw = struct.unpack_from('<I', cdata, so.contract_expiry)[0]
        expiry_year = (expiry_raw >> 16) & 0xFFFF
        if 2000 <= expiry_year <= 2100:
            player.contract_expiry = expiry_raw

        flags = struct.unpack_from('<I', cdata, so.pffl)[0]
        self._apply_contract_flags(player, flags)

        if so.contract_transfer_opts < len(cdata):
            player.contract_transfer_opts = cdata[so.contract_transfer_opts]
        if so.contract_option_years < len(cdata):
            player.contract_option_years = cdata[so.contract_option_years]

        team_ptr = struct.unpack_from('<Q', cdata, so.contract_team)[0]
        return team_ptr

    @staticmethod
    def _apply_contract_flags(player: Player, flags: int):
        """Apply transfer / loan listing flags from the contract bitfield."""
        listed_by_request = bool(flags & (1 << 3))
        set_for_release = bool(flags & (1 << 5))
        available_for_loan = bool(flags & (1 << 1))
        unavailable_for_loan = bool(flags & (1 << 6))

        player.transfer_listed = listed_by_request or set_for_release
        player.loan_listed = available_for_loan and (not unavailable_for_loan)

    # ------------------------------------------------------------------ #
    #  Player traits                                                      #
    # ------------------------------------------------------------------ #

    def _read_traits(self, player: Player):
        """Read player trait bitfield from person address + pprm offset."""
        data = self.reader.read_bytes(player.address + self.so.pprm, 8)
        if not data or len(data) < 8:
            return
        traits: list[str] = []
        for byte_off, bit_idx, name in PLAYER_TRAIT_MAP:
            if byte_off < len(data) and data[byte_off] & (1 << bit_idx):
                traits.append(name)
        player.traits = traits

    # ------------------------------------------------------------------ #
    #  Club / league chain resolution                                     #
    # ------------------------------------------------------------------ #

    def _resolve_club_chain(self, player: Player, team_ptr: int):
        """Follow team -> club -> name and team -> competition chains.

        Resolves club name, league name, league nation, and league continent.
        Results are cached per team_ptr for re-use across players.
        """
        if not team_ptr:
            return

        cached = self._club_cache.get(team_ptr)
        if cached is not None:
            player.club_address = cached[0]
            player.club = cached[1]
            player.league = cached[2]
            player.league_nation = cached[3]
            player.league_continent = cached[4]
            player.league_type = cached[5]
            return

        reader = self.reader
        so = self.so
        club_name = ""
        league_name = ""
        league_nation = ""
        league_continent = ""
        league_type = -1

        # team + 0x30 -> club_ptr -> club + 0xC0 -> name_entry -> string at +4
        club_ptr = reader.read_pointer(team_ptr + so.team_club)
        if club_ptr:
            name_entry = reader.read_pointer(club_ptr + so.club_name_entry)
            if name_entry:
                s = reader.read_string(name_entry + 4, max_len=96)
                if s and s.isprintable():
                    club_name = s

        # team + 0x50 -> competition -> name, nation, continent, type
        comp_ptr = reader.read_pointer(team_ptr + so.team_competition)
        if comp_ptr:
            comp_name_entry = reader.read_pointer(
                comp_ptr + so.competition_name_entry,
            )
            if comp_name_entry:
                s = reader.read_string(comp_name_entry + 4, max_len=96)
                if s and s.isprintable():
                    league_name = s

            type_byte = reader.read_bytes(comp_ptr + so.competition_type, 1)
            if type_byte:
                league_type = type_byte[0]

            nation_ptr = reader.read_pointer(
                comp_ptr + so.competition_nation,
            )
            if nation_ptr:
                nation_name_entry = reader.read_pointer(
                    nation_ptr + so.nation_name,
                )
                if nation_name_entry:
                    s = reader.read_string(nation_name_entry + 4, max_len=64)
                    if s and s.isprintable():
                        league_nation = s

                continent_ptr = reader.read_pointer(
                    nation_ptr + so.nation_continent,
                )
                if continent_ptr:
                    cont_name_entry = reader.read_pointer(
                        continent_ptr + so.continent_name,
                    )
                    if cont_name_entry:
                        s = reader.read_string(cont_name_entry + 4, max_len=64)
                        if s and s.isprintable():
                            league_continent = s

        result = (club_ptr or 0, club_name, league_name, league_nation, league_continent, league_type)
        self._club_cache[team_ptr] = result
        player.club_address = club_ptr or 0
        player.club = club_name
        player.league = league_name
        player.league_nation = league_nation
        player.league_continent = league_continent
        player.league_type = league_type

    # ------------------------------------------------------------------ #
    #  Loan detection                                                     #
    # ------------------------------------------------------------------ #

    def _resolve_loan(self, player: Player, loan_ptr: int):
        """Dereference a loan-contract wrapper and resolve the loan club.

        The pero loan field (pero+0xD0) points to a wrapper object whose
        first pointer ([wrapper+0x00]) is the real loan contract.  The
        loan contract's team field gives the club the player is loaned to.
        """
        if not loan_ptr:
            return

        reader = self.reader
        c_team = self.so.contract_team

        # Dereference wrapper -> real contract
        real_contract = reader.read_pointer(loan_ptr)
        if not real_contract:
            return

        ldata = reader.read_bytes(real_contract, self._CONTRACT_READ_SIZE)
        if ldata is None or len(ldata) < c_team + 8:
            return

        loan_team = struct.unpack_from('<Q', ldata, c_team)[0]
        if loan_team:
            player.parent_club = player.club
            player.parent_club_address = player.club_address
            self._resolve_club_chain(player, loan_team)
            player.on_loan = True

    # ------------------------------------------------------------------ #
    #  Cache management                                                   #
    # ------------------------------------------------------------------ #

    def clear_caches(self):
        """Clear all internal resolution caches.

        Call between successive full scans if the game state has changed
        (e.g. after advancing to a new date).
        """
        self._club_cache.clear()
        self._name_cache.clear()
        self._nation_cache.clear()
