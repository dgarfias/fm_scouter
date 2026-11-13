# FM Scout

A real-time scouting tool for **Football Manager 2024** on Linux (Steam Proton/Wine).

FM Scout reads your save game directly from memory while FM24 is running, giving you instant access to every player, club, and staff member in the game — no need to export files or use in-game views.

## Features

- **Player Search** — Browse and filter all players in the database by name, nationality, club, league, position, ability, potential, age, reputation, and any combination of 40+ attributes.
- **Player Profiles** — Detailed view of any player including attributes, positions (with pitch diagram), personality traits, contract info, and estimated value.
- **Club Viewer** — Overview of every club with squad stats, average ability, and league information.
- **Tactics Builder** — Select a formation and squad, then get a best XI recommendation with role/duty assignments, squad gap analysis, and style recommendations.
- **League Comparison** — Compare your squad's attribute averages against every team in the league, with rankings per attribute.
- **Shortlist** — Mark players of interest and track them separately.
- **CSV Export** — Export player data for use in spreadsheets or other tools.
- **Player Editing** — Edit attributes, positions, personality and CA/PA live
  in the running game (see [Editing the game](#editing-the-game)).
- **Multi-language** — English and Spanish included. Easy to add more languages.

## Requirements

- Football Manager 2024 (version 24.4.2) running on **Linux** via Steam Proton or Wine
- Python 3.10+
- PyQt6

## Installation

```bash
pip install PyQt6
```

## Usage

1. Launch Football Manager 2024 and load a save game.
2. Run FM Scout:

```bash
python main.py
```

3. Click **Scan** to read the game data. The scan takes a few seconds.
4. Use the tabs to search players, view clubs, build tactics, or manage your shortlist.

## How It Works

FM Scout reads the running FM24 process memory to locate game data structures — player attributes, club information, contracts, competition data, and more. It uses signature scanning (AOB patterns) to find key pointers, then follows the game's internal data structures to extract all the information that FM24 itself uses.

The signature patterns and struct offsets are tied to a specific game build. Supported builds are defined as **game profiles** (see below); the scanner probes each profile and adopts the first one that resolves to structurally valid data. The detected build is shown in the status bar after a scan.

## Supported Versions

- **FM24 24.4.2** (built-in profile)

If your Steam install runs a *different* FM build (a newer/older patch, a
repack, a downgraded copy), the scan fails with a clear message instead of a
silent wrong result. To support another build, add a game profile:

1. Drop a JSON file in `game_profiles/` describing the build's AOB
   signatures and offsets (see `game_profiles/README.md` and
   `game_profiles/example.json`).
2. Restart the app and scan — the new profile is probed automatically.

Offsets for a new build are easiest to get from a Cheat Engine table for that
FM version.

## Editing the Game

FM Scout can **write directly to the running game's memory** (attributes,
positions, personality, CA/PA). Because the offsets are version-specific,
edits use the profile that matched the active scan, and every write
re-validates that the memory still holds the same player before touching it —
so a stale address can never corrupt an unrelated object.

Your **save file itself is never touched**. Edits apply to the running
process and will be saved by the game's own save routine (i.e. they stick
when you save). Editing the live process can break a save, so back one up
before experimenting.

## Adding a New Language

1. Copy `locale/en.json` to `locale/xx.json` (where `xx` is the language code, e.g. `fr`, `de`, `pt`).
2. Translate all the string values in the new file.
3. Add the language name to the `"language"` section in both `en.json` and your new file.
4. Restart the app — the new language appears in the dropdown.

## License

This project is for personal and educational use only. Football Manager is a trademark of Sports Interactive / SEGA.
