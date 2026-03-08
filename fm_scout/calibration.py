"""
Calibration utilities for FM24 memory scanning.

Provides helpers for verifying and adjusting offset values
against known player data.
"""


def verify_player_data(player, expected: dict) -> dict:
    """Compare a player's scanned data against expected values.

    Parameters
    ----------
    player : Player
        The scanned player object.
    expected : dict
        Expected values, e.g. {"current_ability": 190, "nationality": "Argentina"}.

    Returns
    -------
    dict
        Mapping of field name -> {"expected": ..., "actual": ..., "match": bool}.
    """
    results = {}
    for key, exp_val in expected.items():
        actual = getattr(player, key, None)
        if actual is None and hasattr(player, "attributes"):
            actual = player.attributes.get(key)
        results[key] = {
            "expected": exp_val,
            "actual": actual,
            "match": actual == exp_val,
        }
    return results


def find_value_in_bytes(data: bytes, value: int, size: int = 1) -> list[int]:
    """Find all offsets in a byte buffer where a value occurs.

    Parameters
    ----------
    data : bytes
        Raw memory bytes to search.
    value : int
        The value to find.
    size : int
        Byte width: 1, 2, or 4.

    Returns
    -------
    list[int]
        List of byte offsets where the value was found.
    """
    import struct
    fmt = {1: '<B', 2: '<H', 4: '<I'}.get(size)
    if fmt is None:
        return []
    results = []
    for off in range(0, len(data) - size + 1):
        if struct.unpack_from(fmt, data, off)[0] == value:
            results.append(off)
    return results
