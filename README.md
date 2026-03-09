# FM Scout

A real-time scouting tool for **Football Manager 2024** on Linux (Steam Proton/Wine).

FM Scout reads your save game directly from memory while FM24 is running, giving you instant access to every player, club, and staff member in the game — no need to export files or use in-game views.

## Features

- **Player Search** — Browse and filter all players in the database by name, nationality, club, league, position, ability, potential, age, reputation, and any combination of 40+ attributes.
- **Player Profiles** — Detailed view of any player including attributes, positions (with pitch diagram), personality traits, contract info, and estimated value.
- **Club Viewer** — Overview of every club with squad stats, average ability, and league information.
- **Tactics Builder** — Select a formation and squad, then get a best XI recommendation with role/duty assignments, squad gap analysis, and style recommendations.
- **My Club** — Automatically detects your current save's manager and club from memory.
- **Shortlist** — Mark players of interest and track them separately.
- **CSV Export** — Export player data for use in spreadsheets or other tools.

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

Your save game is **never modified** — FM Scout is strictly read-only.

## Screenshots

*Coming soon*

## License

This project is for personal and educational use only. Football Manager is a trademark of Sports Interactive / SEGA.
