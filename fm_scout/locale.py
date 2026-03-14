"""Localization support for FM Scout.

Provides a ``tr(key, **kwargs)`` function that looks up strings from
JSON locale files.  Keys are dot-separated, e.g. ``tr("button.scan")``.
Supports ``{placeholder}`` substitution via keyword arguments.
"""

import json
import os
from pathlib import Path

_LOCALE_DIR = Path(__file__).resolve().parent.parent / "locale"
_current_lang: str = "en"
_strings: dict[str, object] = {}
_fallback: dict[str, object] = {}


def _load_locale(lang: str) -> dict[str, object]:
    path = _LOCALE_DIR / f"{lang}.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def set_language(lang: str) -> None:
    global _current_lang, _strings, _fallback
    _current_lang = lang
    _strings = _load_locale(lang)
    if lang != "en":
        _fallback = _load_locale("en")
    else:
        _fallback = {}


def get_language() -> str:
    return _current_lang


def available_languages() -> list[str]:
    langs = []
    if _LOCALE_DIR.is_dir():
        for f in sorted(_LOCALE_DIR.iterdir()):
            if f.suffix == ".json" and f.stem.isalpha():
                langs.append(f.stem)
    return langs


def _resolve(data: dict[str, object], key: str) -> str | None:
    parts = key.split(".")
    node: object = data
    for part in parts:
        if isinstance(node, dict):
            node = node.get(part)
        else:
            return None
    return str(node) if node is not None else None


def tr(key: str, **kwargs: object) -> str:
    """Look up a localized string by dot-separated key.

    Falls back to English, then to the raw key if not found.
    Supports ``{placeholder}`` substitution via keyword arguments.
    """
    result = _resolve(_strings, key)
    if result is None and _fallback:
        result = _resolve(_fallback, key)
    if result is None:
        return key
    if kwargs:
        try:
            result = result.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return result


set_language("en")
