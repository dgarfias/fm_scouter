# Game version profiles

FM Scout is bound to a specific Football Manager build: the AOB signatures
used to find the game's data roots and the struct offsets used to read every
record all depend on the compiled binary.

The built-in profile targets **FM24 24.4.2**. If your install is a different
build (a newer/older patch, a repack, a downgraded copy, etc.) the scan will
fail with a message like:

```
No signature match for game build 'FM24 24.4.2' (game build not supported or AOB changed)
```

To support that build, drop a profile JSON in this folder. The scanner tries
the built-in profile first, then every file here (alphabetically), and adopts
the first one whose signatures resolve to structurally valid player data.

## Profile format

```json
{
  "label": "FM24 24.4.2",
  "aob": {
    "dbt_root": "48 8D 0D ?? ?? ?? ?? 48 8D 15",
    "game_date_ce": "83 F2 01 8B 05 ?? ?? ?? ?? 66 09",
    "game_date_fallback": "48 8B 05 ?? ?? ?? ?? 8B 00",
    "human_manager": "48 8B 35 ?? ?? ?? ?? 48 8B 56 18 ..."
  },
  "person_db_offset": "0x68",
  "table_container_offset": "0x80",
  "struct": {
    "patr": "0x217",
    "ppos": "0x208",
    "pcab": "0x200",
    "ppab": "0x202",
    "pcrp": "0x1FC",
    "pwrp": "0x1FE",
    "pcgv": "0x1B0",
    "pfna": "0x58",
    "psna": "0x60",
    "pcna": "0x68",
    "pnti": "0x70",
    "pdob_day": "0x44",
    "pdob_year": "0x46",
    "pada": "0x78",
    "duni": "0x0C",
    "pcontract": "0xC8",
    "ploan_contract": "0xD0",
    "contract_wage": "0x18",
    "pffl": "0x48",
    "contract_team": "0x10",
    "contract_expiry": "0x40",
    "contract_transfer_opts": "0x56",
    "contract_option_years": "0x57",
    "contract_terms_vec": "0x60",
    "team_club": "0x30",
    "team_competition": "0x50",
    "club_name_entry": "0xC0",
    "competition_name_entry": "0x48",
    "competition_nation": "0x60",
    "competition_type": "0xF4",
    "nation_name": "0x18",
    "nation_continent": "0xF0",
    "continent_name": "0x18",
    "pprm": "0xF0",
    "second_nation_holder": "0x140",
    "second_nation_ptr": "0x48",
    "second_nation_ptr_alt1": "0xA0",
    "second_nation_ptr_alt2": "0x128",
    "player_offset": "0x278",
    "staff_offset": "0xF8",
    "player_staff_offset": "0x138",
    "attr_scale": 5
  },
  "club": {
    "db_offset": "0x10",
    "team_db_offset": "0x98",
    "table_container_offset": "0x80",
    "off_name": "0xC0",
    "off_short_name": "0xC8",
    "off_nation": "0xD8",
    "off_nation_name": "0x18",
    "team_off_club": "0x30",
    "team_off_reputation": "0xA8"
  }
}
```

## Rules

- `label` is required and shown in the status bar when a scan succeeds.
- Every other field is optional; missing values inherit from the built-in
  profile. Only override what actually differs.
- Offsets may be decimal numbers (`535`) or hex strings (`"0x217"`).
- `attribute_byte_offsets` (the byte positions of each attribute inside the
  `Patr` block) is optional too — it rarely changes between FM24 patches, so
  you can usually leave it out.
- `aob` entries are hex byte strings where `??` is a wildcard. Only
  `dbt_root` is required to identify a build; the others are best-effort.
- Files are loaded in alphabetical order; the first one that matches wins.

## Finding the offsets for a new build

The fastest path is a Cheat Engine table for that FM version — the CE tables
used by FMRTE-style tools list the exact pointers/offsets. Map each CE pointer
onto the fields above (e.g. `ptrPlayer -> plao.Patr` is `patr`). The
`dbt_root` AOB is the instruction that loads the database root relative to
RIP; `player_offset` is the value at `type_info + 4` for the player RTTI
record (the back-offset of the player subobject).