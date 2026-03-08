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
        for r in self.regions:
            if 'x' in r.permissions and r.start > 0x100000:
                self.pointers.exe_base = r.start
                return

    def find_code_section(self):
        """Find the main code section (.text / executable region)."""
        exe_base = self.pointers.exe_base
        if not exe_base:
            return
        for r in self.regions:
            if r.start >= exe_base and 'x' in r.permissions and 'r' in r.permissions:
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
        matches = []
        plen = len(pattern)
        for region in regions:
            if 'r' not in region.permissions:
                continue
            data = self.reader.read_bytes(region.start, region.end - region.start)
            if data is None:
                continue
            for i in range(len(data) - plen + 1):
                match = True
                for j in range(plen):
                    if mask[j] != 0 and data[i + j] != pattern[j]:
                        match = False
                        break
                if match:
                    matches.append(region.start + i)
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

        pattern = "48 8B 05 ?? ?? ?? ?? 48 8B 48 ?? 48 8B 41"
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
            target = match_addr + 7 + rip_offset

            dbt_ptr = self.reader.read_pointer(target)
            if dbt_ptr and dbt_ptr != 0:
                test = self.reader.read_pointer(dbt_ptr + 0x68)
                if test and test != 0:
                    self.pointers.dbt_root = dbt_ptr
                    logger.info(f"dbtRoot resolved at {dbt_ptr:#x} (first entry: {test:#x})")
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
        sample_size = min(500, self.pointers.person_count)

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
        pattern = "48 8B 05 ?? ?? ?? ?? 8B 00"
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
                year = (packed >> 16) & 0xFFFF
                day = packed & 0xFFFF
                if 2020 <= year <= 2100 and 1 <= day <= 366:
                    self.pointers.game_date_addr = target
                    self.pointers.game_date_day = day
                    self.pointers.game_date_year = year
                    logger.info(f"Game date: day {day}, year {year}")
                    return True
        return False

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
        return True
