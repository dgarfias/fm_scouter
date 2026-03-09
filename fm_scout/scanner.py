import logging
import struct
from dataclasses import dataclass, field

from .memory import MemoryReader
from .process import MemoryRegion

logger = logging.getLogger('fm_scout.scanner')


def parse_aob_pattern(pattern_str: str) -> tuple[bytes, bytes]:
    """Parse an AOB pattern string like 'AA BB ?? CC' into (pattern_bytes, mask_bytes).
    '??' means wildcard (mask=0), otherwise mask=0xFF."""
    parts = pattern_str.strip().split()
    pattern = bytearray()
    mask = bytearray()
    for p in parts:
        if p == '??' or p == '?':
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

    def __init__(self, reader: MemoryReader, regions: list[MemoryRegion]):
        self.reader = reader
        self.regions = regions
        self.pointers = GamePointers()
        self.player_vtables: set[int] = set()

    def find_exe_base(self):
        """Find fm.exe base address from memory regions."""
        for r in self.regions:
            if 'fm.exe' in r.path.lower() and 'r' in r.permissions:
                self.pointers.exe_base = r.start
                return

    def find_code_section(self):
        """Find the main code section (r-xp region right after fm.exe base)."""
        exe_base = self.pointers.exe_base
        if not exe_base:
            return
        for r in self.regions:
            if (r.start >= exe_base
                    and 'x' in r.permissions
                    and 'r' in r.permissions
                    and 'w' not in r.permissions
                    and (r.end - r.start) > 1_000_000):
                self.pointers.code_start = r.start
                self.pointers.code_end = r.end
                size_mb = (r.end - r.start) // (1024 * 1024)
                logger.info(f"Code section: {r.start:#x}-{r.end:#x} ({size_mb}MB)")
                return

    def scan_for_pattern(self, pattern_str: str, regions: list[MemoryRegion] = None) -> list[int]:
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

        anchor = pattern[best_start:best_start + best_len]
        matches: list[int] = []

        for region in regions:
            if 'r' not in region.permissions:
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

    def resolve_dbt_root(self) -> bool:
        """Find dbtRoot via AOB scan for the dbtRoot pattern."""
        code_regions = [r for r in self.regions
                        if r.start >= self.pointers.code_start
                        and r.end <= self.pointers.code_end
                        and 'r' in r.permissions]
        if not code_regions:
            code_regions = [r for r in self.regions
                            if 'x' in r.permissions and 'r' in r.permissions]

        pattern = "48 8D 0D ?? ?? ?? ?? 48 8D 15"
        logger.info(
            f"Scanning region {self.pointers.code_start:#x}-{self.pointers.code_end:#x} "
            f"({(self.pointers.code_end - self.pointers.code_start) // (1024 * 1024)}MB)"
        )

        matches = self.scan_for_pattern(pattern, code_regions)
        logger.info(f"Found {len(matches)} dbtRoot pattern match(es)")

        if not matches:
            return False

        for match_addr in matches:
            data = self.reader.read_bytes(match_addr, 16)
            if data is None:
                continue
            rip_offset = struct.unpack_from('<i', data, 3)[0]
            dbt_ptr = match_addr + 7 + rip_offset

            person_db = self.reader.read_pointer(dbt_ptr + 0x68)
            if not person_db or person_db == 0:
                continue
            table_ptr = self.reader.read_pointer(person_db + 0x80)
            if not table_ptr or table_ptr == 0:
                continue
            tbl_start = self.reader.read_pointer(table_ptr)
            tbl_end = self.reader.read_pointer(table_ptr + 8)
            if tbl_start and tbl_end and tbl_end > tbl_start:
                count = (tbl_end - tbl_start) // 8
                if 1000 < count < 500_000:
                    self.pointers.dbt_root = dbt_ptr
                    logger.info(f"dbtRoot resolved at {dbt_ptr:#x} (first entry: {hex(person_db)})")
                    return True
        return False

    def resolve_person_table(self) -> bool:
        """Resolve PersonTable from dbtRoot + 0x68."""
        dbt = self.pointers.dbt_root
        if not dbt:
            return False

        person_db = self.reader.read_pointer(dbt + 0x68)
        if not person_db:
            return False

        table_ptr = self.reader.read_pointer(person_db + 0x80)
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

    def discover_vtables(self) -> bool:
        """Discover player vtable addresses by examining person objects."""
        if self.pointers.person_table_start == 0:
            return False

        vtable_counts: dict[int, int] = {}
        sample_size = min(5000, self.pointers.person_count)

        for i in range(sample_size):
            ptr_addr = self.pointers.person_table_start + i * 8
            person_ptr = self.reader.read_pointer(ptr_addr)
            if person_ptr is None or person_ptr == 0:
                continue

            vtable = self.reader.read_pointer(person_ptr)
            if vtable is None or vtable == 0:
                continue

            vtable_counts[vtable] = vtable_counts.get(vtable, 0) + 1

        if not vtable_counts:
            logger.warning("Could not discover any vtables")
            return False

        from .offsets import STRUCT_OFFSETS
        for vt, count in sorted(vtable_counts.items(), key=lambda x: -x[1]):
            type_info = self.reader.read_pointer(vt - 8)
            if type_info is None or type_info == 0:
                continue
            offset_val = self.reader.read_uint32(type_info + 4)
            if offset_val is None or offset_val > 0x1000:
                continue
            if offset_val == STRUCT_OFFSETS.player_offset:
                self.player_vtables.add(vt)

        logger.info(f"Discovered {len(vtable_counts)} distinct vtable values:")
        for vt, count in sorted(vtable_counts.items(), key=lambda x: -x[1]):
            logger.info(f"  vtable={vt:#x} count={count}")

        return len(self.player_vtables) > 0

    def find_game_date(self) -> bool:
        """Find the current game date via datTimeRoot AOB."""
        code_regions = [r for r in self.regions
                        if r.start >= self.pointers.code_start
                        and r.end <= self.pointers.code_end
                        and 'r' in r.permissions]
        if not code_regions:
            code_regions = [r for r in self.regions
                            if 'x' in r.permissions and 'r' in r.permissions]

        logger.info(
            f"Scanning region {self.pointers.code_start:#x}-{self.pointers.code_end:#x} "
            f"({(self.pointers.code_end - self.pointers.code_start) // (1024 * 1024)}MB)"
        )

        # FM24 (24.4.2) signature from CE table:
        #   83 F2 01 8B 05 ?? ?? ?? ?? 66 09
        # datTimeRoot = RIP-relative target of the MOV at +3 (disp32 at +5)
        ce_pattern = "83 F2 01 8B 05 ?? ?? ?? ?? 66 09"
        ce_matches = self.scan_for_pattern(ce_pattern, code_regions)
        for match_addr in ce_matches:
            data = self.reader.read_bytes(match_addr, 16)
            if data is None or len(data) < 10:
                continue
            rip_offset = struct.unpack_from('<i', data, 5)[0]
            target = match_addr + 9 + rip_offset
            packed = self.reader.read_uint32(target)
            year_raw = self.reader.read_bytes(target + 2, 2)
            if packed is None or not year_raw or len(year_raw) < 2:
                continue
            year = struct.unpack('<H', year_raw)[0]
            # Current day is stored in low 9 bits (Mask 0x1FF in CE table)
            day = packed & 0x1FF
            if 2020 <= year <= 2100 and 1 <= day <= 366:
                self.pointers.game_date_addr = target
                self.pointers.game_date_day = day
                self.pointers.game_date_year = year
                logger.info(f"Game date: day {day}, year {year}")
                return True

        # Older fallback signature
        pattern = "48 8B 05 ?? ?? ?? ?? 8B 00"
        matches = self.scan_for_pattern(pattern, code_regions)
        for match_addr in matches:
            data = self.reader.read_bytes(match_addr, 16)
            if data is None:
                continue
            rip_offset = struct.unpack_from('<i', data, 3)[0]
            target = match_addr + 7 + rip_offset

            date_data = self.reader.read_bytes(target, 4)
            if date_data:
                packed = struct.unpack('<I', date_data)[0]
                year16 = (packed >> 16) & 0xFFFF
                day16 = packed & 0xFFFF
                if 2020 <= year16 <= 2100 and 1 <= day16 <= 366:
                    self.pointers.game_date_addr = target
                    self.pointers.game_date_day = day16
                    self.pointers.game_date_year = year16
                    logger.info(f"Game date: day {day16}, year {year16}")
                    return True
        return False

    def resolve_human_manager_club(self) -> str | None:
        """Resolve the current human manager's club name from memory."""
        from .offsets import STRUCT_OFFSETS

        code_regions = [r for r in self.regions
                        if r.start >= self.pointers.code_start
                        and r.end <= self.pointers.code_end
                        and 'r' in r.permissions]
        if not code_regions:
            code_regions = [r for r in self.regions
                            if 'x' in r.permissions and 'r' in r.permissions]

        # CE: HUMAN_NON_PLAYER_MANAGER
        # aob: 48 8B 35 ?? ?? ?? ?? 48 8B 56 18 4C 8B 76 20 49 29 D6 B0 01 49 83 FE 10
        pattern = (
            "48 8B 35 ?? ?? ?? ?? 48 8B 56 18 4C 8B 76 20 "
            "49 29 D6 B0 01 49 83 FE 10"
        )
        matches = self.scan_for_pattern(pattern, code_regions)
        if not matches:
            return None

        for match_addr in matches:
            data = self.reader.read_bytes(match_addr, 12)
            if data is None or len(data) < 7:
                continue
            rel = struct.unpack_from('<i', data, 3)[0]
            ptr_addr = match_addr + 7 + rel
            root_ptr = self.reader.read_pointer(ptr_addr)
            if not root_ptr:
                continue

            manager_bases: list[int] = []
            vec_start = self.reader.read_pointer(root_ptr + 0x18)
            vec_end = self.reader.read_pointer(root_ptr + 0x20)
            if vec_start and vec_end and vec_end > vec_start and (vec_end - vec_start) <= 0x2000:
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

                    uid = self.reader.read_uint32(person_ptr + STRUCT_OFFSETS.duni)
                    if not uid:
                        continue

                    contract_ptr = self.reader.read_pointer(person_ptr + STRUCT_OFFSETS.pcontract)
                    if not contract_ptr:
                        continue
                    team_ptr = self.reader.read_pointer(contract_ptr + STRUCT_OFFSETS.contract_team)
                    if not team_ptr:
                        continue
                    club_ptr = self.reader.read_pointer(team_ptr + STRUCT_OFFSETS.team_club)
                    if not club_ptr:
                        continue
                    name_entry = self.reader.read_pointer(club_ptr + STRUCT_OFFSETS.club_name_entry)
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
                        staff_ptr, person_ptr, club_name,
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
            val = struct.unpack_from('<Q', raw, i * 8)[0]
            if val != 0:
                ptrs.append(val)
        return ptrs

    def scan_all(self, person_table_offset: int = 0x68,
                 container_offset: int = 0x80) -> bool:
        """Run the full scan sequence."""
        self.find_exe_base()
        logger.info(f"EXE base: {self.pointers.exe_base:#x}")

        self.find_code_section()
        if not self.resolve_dbt_root():
            return False
        if not self.resolve_person_table():
            return False
        self.discover_vtables()
        self.find_game_date()
        self.resolve_human_manager_club()
        return True
