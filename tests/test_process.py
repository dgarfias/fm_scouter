import io
import unittest
from unittest.mock import patch

from fm_scout.process import find_fm_process


class FindFmProcessTests(unittest.TestCase):
    def find(self, processes):
        def open_proc(path, mode="r"):
            _, _, pid, entry = path.split("/")
            command, name = processes[pid]
            if entry == "cmdline":
                return io.BytesIO(command)
            return io.StringIO(name)

        with (
            patch("fm_scout.process.os.listdir", return_value=list(processes)),
            patch("builtins.open", side_effect=open_proc),
            patch("fm_scout.process.os.readlink", return_value="/proton/wine-preloader"),
        ):
            return find_fm_process()

    def test_selects_game_on_any_wine_drive_not_steam_helper(self):
        result = self.find({
            "10": (b"c:\\windows\\system32\\steam.exe\0/game/fm.exe\0", "steam.exe"),
            "11": (b"S:\\steamapps\\common\\Football Manager 2024\\fm.exe\0", "Main Thread"),
        })
        self.assertEqual(result.pid, 11)

    def test_launchers_alone_are_not_the_game(self):
        self.assertIsNone(self.find({
            "10": (b"/proton/python3\0proton\0/game/fm.exe\0", "python3"),
            "11": (b"c:\\windows\\system32\\steam.exe\0/game/fm.exe\0", "steam.exe"),
            "12": (b"/reaper\0/game/fm.exe\0", "reaper"),
        }))

    def test_unix_game_path_and_case_insensitive_name(self):
        result = self.find({"10": (b"/games/FM.EXE\0", "Main Thread")})
        self.assertEqual(result.pid, 10)

    def test_process_name_fallback(self):
        result = self.find({"10": (b"wine\0", "fm.exe")})
        self.assertEqual(result.pid, 10)

    def test_no_processes(self):
        self.assertIsNone(self.find({}))
