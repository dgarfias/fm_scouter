import logging
import struct
from collections import Counter
from dataclasses import dataclass, field

from .memory import MemoryReader
from .offsets import DEFAULT_PROFILE, VersionProfile
from .process import MemoryRegion

logger = logging.getLogger("fm_scout.scanner")


def parse_aob_pattern(pattern_str: str) -> tuple[bytes, bytes]:
    """Parse an AOB pattern string like 'AA BB ?? CC' into (pattern_bytes, mask_bytes).
    '??' means wildcard (mask=0), otherwise mask=0xFF."""
    parts = pattern_str.strip().split()
    pattern = bytearray()
    mask = bytearray()
    for p in parts:
        if p == "??" or p == "?":
            pattern.append(0)
            mask.append(0)
        else:
            pattern.append(int(p, 16))
            mask.append(0xFF)
    return bytes(pattern), bytes(mask)


@dataclass
class GamePointers:
    exe_base: int = 0
    code_start: int = 0
    code_end: int = 0
    dbt_root: int = 0
    person_table_start: int = 0
    person_table_end: int = 0
    person_count: int = 0
    game_date_addr: int = 0
    game_date_day: int = 0
    game_date_year: int = 0
    human_staff_addr: int = 0
    human_person_addr: int = 0
    human_club_name: str = ""


class GameScanner:
    """Scan FM24 process memory to locate game data structures."""

    def __init__(
        self,
        reader: MemoryReader,
        regions: list[MemoryRegion],
        profiles: list[VersionProfile] | None = None,
    ):
        self.reader = reader
        self.regions = regions
        self.profiles = list(profiles) if profiles else [DEFAULT_PROFILE]
        self.profile: VersionProfile | None = None
        self.pointers = GamePointers()
        self.player_vtables: set[int] = set()
        self.last_error = ""

    def find_exe_base(self):
        """Find fm.exe base address from memory regions."""
        for r in self.regions:
            if "fm.exe" in r.path.lower() and "r" in r.permissions:
                self.pointers.exe_base = r.start
                return

    def _code_regions(self) -> list[MemoryRegion]:
        """Return the regions to scan for code signatures.

        The game's compiled code lives in readable+executable regions.
        Rather than trusting the layout of a single code section right
        after ``fm.exe`` (which varies between Wine/Proton versions and
        installs), scan every such region.  If none are executable, fall
        back to any readable region so a mismatched mapping never aborts
        the AOB scan.  Oversized file-backed mappings are skipped because
        they are memory-mapped data, not code.
        """
        usable = [
            r
            for r in self.regions
            if "r" in r.permissions and "x" in r.permissions
        ]
        if not usable:
            usable = [r for r in self.regions if "r" in r.permissions]
        capped = [
            r for r in usable if (r.end - r.start) <= 512 * 1024 * 1024
        ]
        return capped or usable

    def find_code_section(self):
        """Locate the main code section for informational logging."""
        exe_base = self.pointers.exe_base
        if not exe_base:
            return
        for r in self.regions:
            if (
                r.start >= exe_base
                and "x" in r.permissions
                and "r" in r.permissions
                and "w" not in r.permissions
                and (r.end - r.start) > 1_000_000
            ):
                self.pointers.code_start = r.start
                self.pointers.code_end = r.end
                size_mb = (r.end - r.start) // (1024 * 1024)
                logger.info(f"Code section: {r.start:#x}-{r.end:#x} ({size_mb}MB)")
                return

    def scan_for_pattern(
        self, pattern_str: str, regions: list[MemoryRegion] = None
    ) -> list[int]:
        """Scan memory regions for an AOB pattern."""
        pattern, mask = parse_aob_pattern(pattern_str)
        if regions is None:
            regions = self.regions
        plen = len(pattern)
        if plen == 0:
            return []

        # Fast path: choose the longest fixed-byte run as anchor and use
        # bytes.find() to locate candidates, then verify masked bytes.
        fixed_positions = [i for i, m in enumerate(mask) if m != 0]
        if not fixed_positions:
            return []

        best_start = 0
        best_len = 0
        i = 0
        while i < plen:
            if mask[i] == 0:
                i += 1
                continue
            run_start = i
            while i < plen and mask[i] != 0:
                i += 1
            run_len = i - run_start
            if run_len > best_len:
                best_start = run_start
                best_len = run_len

        anchor = pattern[best_start : best_start + best_len]
        matches: list[int] = []

        for region in regions:
            if "r" not in region.permissions:
                continue
            data = self.reader.read_bytes(region.start, region.end - region.start)
            if data is None or len(data) < plen:
                continue

            data_len = len(data)
            search_pos = 0
            while True:
                anchor_pos = data.find(anchor, search_pos)
                if anchor_pos < 0:
                    break
                candidate = anchor_pos - best_start
                if 0 <= candidate and candidate + plen <= data_len:
                    ok = True
                    for j in fixed_positions:
                        if data[candidate + j] != pattern[j]:
                            ok = False
                            break
                    if ok:
                        matches.append(region.start + candidate)
                search_pos = anchor_pos + 1
        return matches

    def resolve_dbt_root(self, profile: VersionProfile | None = None) -> bool:
        """Find dbtRoot via AOB scan for the given profile's signature."""
        profile = profile or self.profile
        code_regions = self._code_regions()
        pattern = profile.aob.get("dbt_root")
        if not pattern:
            self.last_error = f"Profile '{profile.label}' has no dbt_root signature"
            return False

        logger.info(
            f"Scanning {sum(r.end - r.start for r in code_regions) // (1024 * 1024)}MB "
            f"({len(code_regions)} region(s)) for '{profile.label}' dbtRoot"
        )

        matches = self.scan_for_pattern(pattern, code_regions)
        logger.info(f"Found {len(matches)} dbtRoot pattern match(es)")

        if not matches:
            self.last_error = (
                f"No signature match for game build '{profile.label}' "
                "(game build not supported or AOB changed)"
            )
            return False

        person_db_offset = profile.person_db_offset
        table_container_offset = profile.table_container_offset
        player_offset = profile.struct.player_offset

        candidates: list[tuple[int, int, int, int]] = []
        seen_tables: set[tuple[int, int]] = set()
        for match_addr in matches:
            data = self.reader.read_bytes(match_addr, 16)
            if data is None:
                continue
            rip_offset = struct.unpack_from("<i", data, 3)[0]
            dbt_ptr = match_addr + 7 + rip_offset

            person_db = self.reader.read_pointer(dbt_ptr + person_db_offset)
            if not person_db or person_db == 0:
                continue
            table_ptr = self.reader.read_pointer(person_db + table_container_offset)
            if not table_ptr or table_ptr == 0:
                continue
            tbl_start = self.reader.read_pointer(table_ptr)
            tbl_end = self.reader.read_pointer(table_ptr + 8)
            if tbl_start and tbl_end and tbl_end > tbl_start:
                count = (tbl_end - tbl_start) // 8
                if 1000 < count < 500_000:
                    table_key = (tbl_start, tbl_end)
                    if table_key not in seen_tables:
                        seen_tables.add(table_key)
                        candidates.append((dbt_ptr, tbl_start, tbl_end, count))

        if not candidates:
            self.last_error = (
                f"Signature for '{profile.label}' matched but no valid person "
                "table was found"
            )
            return False

        # The signature has multiple structurally plausible matches in FM24.
        # Select the table that actually contains player RTTI instead of
        # accepting whichever match happens to appear first in the code scan.
        scored: list[tuple[int, int, int, int]] = []
        for dbt_ptr, tbl_start, tbl_end, count in candidates:
            raw = self.reader.read_bytes(tbl_start, tbl_end - tbl_start)
            if not raw:
                continue
            pointers = [
                struct.unpack_from("<Q", raw, i * 8)[0]
                for i in range(count)
                if struct.unpack_from("<Q", raw, i * 8)[0]
            ]
            if not pointers:
                continue

            sample_count = min(4096, len(pointers))
            if sample_count == len(pointers):
                sample = pointers
            else:
                last = len(pointers) - 1
                sample = [
                    pointers[(i * last) // (sample_count - 1)]
                    for i in range(sample_count)
                ]

            vtable_counts = Counter(
                vtable for _, vtable in self.reader.batch_read_u64(sample) if vtable
            )
            player_hits = 0
            for vtable, occurrences in vtable_counts.items():
                type_info = self.reader.read_pointer(vtable - 8)
                if type_info and (
                    self.reader.read_uint32(type_info + 4)
                    == player_offset
                ):
                    player_hits += occurrences

            logger.info(
                "dbtRoot candidate %#x: %d entries, %d/%d sampled players",
                dbt_ptr,
                count,
                player_hits,
                sample_count,
            )
            scored.append((player_hits, len(pointers), count, dbt_ptr))

        if not scored:
            self.last_error = (
                f"Signature for '{profile.label}' matched but no candidate "
                "contained player objects"
            )
            return False

        player_hits, _, count, dbt_ptr = max(scored)
        if player_hits <= 0:
            self.last_error = (
                f"No dbtRoot candidate for '{profile.label}' contained player objects"
            )
            return False

        self.pointers.dbt_root = dbt_ptr
        logger.info("dbtRoot resolved at %#x (%d person entries)", dbt_ptr, count)
        return True

    def resolve_person_table(
        self, profile: VersionProfile | None = None
    ) -> bool:
        """Resolve PersonTable from dbtRoot + profile.person_db_offset."""
        profile = profile or self.profile
        dbt = self.pointers.dbt_root
        if not dbt:
            return False

        person_db = self.reader.read_pointer(dbt + profile.person_db_offset)
        if not person_db:
            return False

        table_ptr = self.reader.read_pointer(
            person_db + profile.table_container_offset
        )
        if not table_ptr:
            return False

        start = self.reader.read_pointer(table_ptr)
        end = self.reader.read_pointer(table_ptr + 8)
        if not start or not end or end <= start:
            return False

        count = (end - start) // 8
        self.pointers.person_table_start = start
        self.pointers.person_table_end = end
        self.pointers.person_count = count
        logger.info(f"PersonTable: {count} entries ({start:#x} - {end:#x})")
        return True

    def discover_vtables(
        self, profile: VersionProfile | None = None
    ) -> bool:
        """Discover player vtable addresses by examining person objects."""
        profile = profile or self.profile
        if self.pointers.person_table_start == 0:
            return False

        raw = self.reader.read_bytes(
            self.pointers.person_table_start,
            self.pointers.person_table_end - self.pointers.person_table_start,
        )
        if not raw:
            return False

        person_ptrs = [
            struct.unpack_from("<Q", raw, i * 8)[0]
            for i in range(self.pointers.person_count)
            if struct.unpack_from("<Q", raw, i * 8)[0]
        ]
        sample_size = min(20_000, len(person_ptrs))
        if sample_size == len(person_ptrs):
            sample = person_ptrs
        else:
            last = len(person_ptrs) - 1
            sample = [
                person_ptrs[(i * last) // (sample_size - 1)]
                for i in range(sample_size)
            ]

        vtable_counts = Counter(
            vtable for _, vtable in self.reader.batch_read_u64(sample) if vtable
        )

        if not vtable_counts:
            logger.warning("Could not discover any vtables")
            return False

        for vt, count in sorted(vtable_counts.items(), key=lambda x: -x[1]):
            type_info = self.reader.read_pointer(vt - 8)
            if type_info is None or type_info == 0:
                continue
            offset_val = self.reader.read_uint32(type_info + 4)
            if offset_val is None or offset_val > 0x1000:
                continue
            if offset_val == profile.struct.player_offset:
                self.player_vtables.add(vt)

        logger.info(
            "Discovered %d player vtable(s) from %d distributed person samples",
            len(self.player_vtables),
            sample_size,
        )

        return len(self.player_vtables) > 0

    def find_game_date(
        self, profile: VersionProfile | None = None
    ) -> bool:
        """Find the current game date via the datTimeRoot AOB."""
        profile = profile or self.profile
        code_regions = self._code_regions()

        # FM24 (24.4.2) signature from CE table:
        #   83 F2 01 8B 05 ?? ?? ?? ?? 66 09
        # datTimeRoot = RIP-relative target of the MOV at +3 (disp32 at +5)
        ce_pattern = profile.aob.get("game_date_ce")
        ce_matches = self.scan_for_pattern(ce_pattern, code_regions) if ce_pattern else []
        for match_addr in ce_matches:
            data = self.reader.read_bytes(match_addr, 16)
            if data is None or len(data) < 10:
                continue
            rip_offset = struct.unpack_from("<i", data, 5)[0]
            target = match_addr + 9 + rip_offset
            packed = self.reader.read_uint32(target)
            year_raw = self.reader.read_bytes(target + 2, 2)
            if packed is None or not year_raw or len(year_raw) < 2:
                continue
            year = struct.unpack("<H", year_raw)[0]
            # Current day is stored in low 9 bits (Mask 0x1FF in CE table)
            day = packed & 0x1FF
            if 2020 <= year <= 2100 and 1 <= day <= 366:
                self.pointers.game_date_addr = target
                self.pointers.game_date_day = day
                self.pointers.game_date_year = year
                logger.info(f"Game date: day {day}, year {year}")
                return True

        # Older fallback signature
        pattern = profile.aob.get("game_date_fallback")
        if not pattern:
            return False
        matches = self.scan_for_pattern(pattern, code_regions)
        for match_addr in matches:
            data = self.reader.read_bytes(match_addr, 16)
            if data is None:
                continue
            rip_offset = struct.unpack_from("<i", data, 3)[0]
            target = match_addr + 7 + rip_offset

            date_data = self.reader.read_bytes(target, 4)
            if date_data:
                packed = struct.unpack("<I", date_data)[0]
                year16 = (packed >> 16) & 0xFFFF
                day16 = packed & 0xFFFF
                if 2020 <= year16 <= 2100 and 1 <= day16 <= 366:
                    self.pointers.game_date_addr = target
                    self.pointers.game_date_day = day16
                    self.pointers.game_date_year = year16
                    logger.info(f"Game date: day {day16}, year {year16}")
                    return True
        return False

    def resolve_human_manager_club(
        self, profile: VersionProfile | None = None
    ) -> str | None:
        """Resolve the current human manager's club name from memory."""
        profile = profile or self.profile
        code_regions = self._code_regions()

        # CE: HUMAN_NON_PLAYER_MANAGER
        # aob: 48 8B 35 ?? ?? ?? ?? 48 8B 56 18 4C 8B 76 20 49 29 D6 B0 01 49 83 FE 10
        pattern = profile.aob.get("human_manager")
        if not pattern:
            return None
        matches = self.scan_for_pattern(pattern, code_regions)
        if not matches:
            return None

        for match_addr in matches:
            data = self.reader.read_bytes(match_addr, 12)
            if data is None or len(data) < 7:
                continue
            rel = struct.unpack_from("<i", data, 3)[0]
            ptr_addr = match_addr + 7 + rel
            root_ptr = self.reader.read_pointer(ptr_addr)
            if not root_ptr:
                continue

            manager_bases: list[int] = []
            vec_start = self.reader.read_pointer(root_ptr + 0x18)
            vec_end = self.reader.read_pointer(root_ptr + 0x20)
            if (
                vec_start
                and vec_end
                and vec_end > vec_start
                and (vec_end - vec_start) <= 0x2000
            ):
                for addr in range(vec_start, vec_end, 8):
                    base = self.reader.read_pointer(addr)
                    if base:
                        manager_bases.append(base)
            if not manager_bases:
                manager_bases.append(root_ptr)

            for staff_ptr in manager_bases:
                # Human manager objects embed the person object at a positive
                # offset. Detect that offset dynamically by checking the
                # vtable back-offset metadata (type_info+4).
                for person_off in range(0x80, 0x901, 8):
                    person_ptr = staff_ptr + person_off
                    vtable = self.reader.read_pointer(person_ptr)
                    if not vtable:
                        continue
                    type_info = self.reader.read_pointer(vtable - 8)
                    if not type_info:
                        continue
                    back_off = self.reader.read_uint32(type_info + 4)
                    if back_off != person_off:
                        continue

                    uid = self.reader.read_uint32(person_ptr + profile.struct.duni)
                    if not uid:
                        continue

                    contract_ptr = self.reader.read_pointer(
                        person_ptr + profile.struct.pcontract
                    )
                    if not contract_ptr:
                        continue
                    team_ptr = self.reader.read_pointer(
                        contract_ptr + profile.struct.contract_team
                    )
                    if not team_ptr:
                        continue
                    club_ptr = self.reader.read_pointer(
                        team_ptr + profile.struct.team_club
                    )
                    if not club_ptr:
                        continue
                    name_entry = self.reader.read_pointer(
                        club_ptr + profile.struct.club_name_entry
                    )
                    if not name_entry:
                        continue

                    club_name = self.reader.read_string(name_entry + 4, max_len=96)
                    if not club_name or not club_name.isprintable():
                        head = self.reader.read_pointer(name_entry)
                        if head:
                            club_name = self.reader.read_string(head + 4, max_len=96)
                    if not club_name or not club_name.isprintable():
                        continue

                    self.pointers.human_staff_addr = staff_ptr
                    self.pointers.human_person_addr = person_ptr
                    self.pointers.human_club_name = club_name
                    logger.info(
                        "Human manager resolved: staff=%#x person=%#x club=%s",
                        staff_ptr,
                        person_ptr,
                        club_name,
                    )
                    return club_name
        return None

    def get_person_pointers(self) -> list[int]:
        """Read all person pointers from the person table."""
        start = self.pointers.person_table_start
        end = self.pointers.person_table_end
        if not start or not end:
            return []

        size = end - start
        raw = self.reader.read_bytes(start, size)
        if raw is None:
            return []

        count = size // 8
        ptrs = []
        for i in range(count):
            val = struct.unpack_from("<Q", raw, i * 8)[0]
            if val != 0:
                ptrs.append(val)
        return ptrs

    def _try_profile(self, profile: VersionProfile) -> bool:
        """Attempt a full resolution run against a single build profile.

        A profile is only adopted once its dbtRoot signature resolves to a
        structurally valid person table (containing reachable player
        objects with the right RTTI back-offset).
        """
        self.pointers = GamePointers()
        self.player_vtables = set()
        self.last_error = ""

        if not self.resolve_dbt_root(profile):
            return False
        if not self.resolve_person_table(profile):
            self.last_error = (
                f"Resolved dbtRoot for '{profile.label}' but person table "
                "could not be read"
            )
            return False

        self.discover_vtables(profile)
        self.find_game_date(profile)
        self.resolve_human_manager_club(profile)
        self.profile = profile
        logger.info("Matched game profile: %s", profile.label)
        return True

    def scan_all(self) -> bool:
        """Run the full scan sequence, probing each known game profile."""
        self.find_exe_base()
        self.find_code_section()
        self.last_error = ""
        first_error = ""
        for profile in self.profiles:
            if self._try_profile(profile):
                return True
            if not first_error:
                first_error = self.last_error

        if first_error:
            self.last_error = (
                f"{first_error} (tried {len(self.profiles)} game profile(s))"
            )
        else:
            self.last_error = "No supported game version matched"
        logger.error("Scan failed: %s", self.last_error)
        return False
