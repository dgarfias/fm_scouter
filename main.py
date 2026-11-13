#!/usr/bin/env python3
import csv
import logging
import math
import os
import signal
import sys
import unicodedata
from datetime import date, timedelta
from typing import Optional

from PyQt6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QItemSelectionModel,
    QModelIndex,
    QPoint,
    QRect,
    QRectF,
    QSettings,
    QSize,
    Qt,
    QThread,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPalette, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListView,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStatusBar,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionTab,
    QStyleOptionViewItem,
    QStylePainter,
    QTabBar,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from fm_scout.club import ClubReader, enrich_clubs_with_players
from fm_scout.club_ui import ClubViewerWidget
from fm_scout.currency import (
    DEFAULT_GBP_TO_EUR_RATE,
    format_eur_from_gbp,
    gbp_to_eur,
    get_gbp_to_eur_rate,
    set_gbp_to_eur_rate,
)
from fm_scout.locale import tr
from fm_scout.memory import MemoryReader
from fm_scout.offsets import (
    ATTR_OFFSETS,
    PERSONALITY_NAMES,
    POSITION_NAMES,
)
from fm_scout.player import Player, PlayerAttributes, PlayerReader
from fm_scout.process import find_fm_process, get_memory_regions
from fm_scout.profiles import get_profiles
from fm_scout.scanner import GameScanner
from fm_scout.tactics_ui import TacticsBuilderWidget
from fm_scout.writer import (
    MemoryWriter,
    PlayerWriteError,
    PlayerWriter,
    build_export,
    export_to_file,
    import_from_file,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("fm_scout")


# ---------------------------------------------------------------------------
# Column / attribute constants
# ---------------------------------------------------------------------------

ATTR_COLUMNS = (
    ATTR_OFFSETS.TECHNICAL_FIELDS
    + ATTR_OFFSETS.MENTAL_FIELDS
    + ATTR_OFFSETS.PHYSICAL_FIELDS
    + ATTR_OFFSETS.GOALKEEPER_FIELDS
    + ATTR_OFFSETS.HIDDEN_FIELDS
)

PERSONALITY_COLS = [f"pers_{name.lower()}" for name in PERSONALITY_NAMES]


def _build_short_names() -> dict[str, str]:
    all_attrs = (
        ATTR_OFFSETS.TECHNICAL_FIELDS
        + ATTR_OFFSETS.MENTAL_FIELDS
        + ATTR_OFFSETS.PHYSICAL_FIELDS
        + ATTR_OFFSETS.GOALKEEPER_FIELDS
        + ATTR_OFFSETS.HIDDEN_FIELDS
    )
    return {a: tr(f"attr_short.{a}") for a in all_attrs}


def _build_full_names() -> dict[str, str]:
    all_attrs = (
        ATTR_OFFSETS.TECHNICAL_FIELDS
        + ATTR_OFFSETS.MENTAL_FIELDS
        + ATTR_OFFSETS.PHYSICAL_FIELDS
        + ATTR_OFFSETS.GOALKEEPER_FIELDS
        + ATTR_OFFSETS.HIDDEN_FIELDS
    )
    return {a: tr(f"attr.{a}") for a in all_attrs}


SHORT_NAMES = _build_short_names()
FULL_NAMES = _build_full_names()

CONTRACT_EXTRA_COLS = [
    "transfer_listed",
    "loan_listed",
    "on_loan",
    "parent_club",
    "league",
    "contract_expiry",
    "contract_transfer_opts",
    "contract_option_years",
    "listed_reason",
]

DEFAULT_VISIBLE_COLS = [
    "name",
    "club",
    "nationality",
    "age",
    "best_pos",
    "est_value",
    "wage",
    "ca",
    "pa",
    "reputation",
]

TABLE_COLS = (
    DEFAULT_VISIBLE_COLS + CONTRACT_EXTRA_COLS + list(ATTR_COLUMNS) + PERSONALITY_COLS
)

COL_INDEX = {name: idx for idx, name in enumerate(TABLE_COLS)}

DEFAULT_HIDDEN_COLS = set(TABLE_COLS) - set(DEFAULT_VISIBLE_COLS)

TABLE_LAYOUT_VERSION = 6


def _build_col_headers() -> dict[str, str]:
    h: dict[str, str] = {}
    for col in (
        "name",
        "club",
        "nationality",
        "age",
        "best_pos",
        "est_value",
        "wage",
        "ca",
        "pa",
        "reputation",
        "transfer_listed",
        "loan_listed",
        "on_loan",
        "parent_club",
        "league",
        "contract_expiry",
        "contract_transfer_opts",
        "contract_option_years",
        "listed_reason",
    ):
        h[col] = tr(f"column.{col}")
    for a in ATTR_COLUMNS:
        h[a] = SHORT_NAMES[a]
    for pc in PERSONALITY_COLS:
        h[pc] = pc[5:].title()[:4]
    return h


def _build_menu_headers() -> dict[str, str]:
    h: dict[str, str] = {}
    for col in (
        "name",
        "club",
        "nationality",
        "age",
        "best_pos",
        "est_value",
        "wage",
        "ca",
        "pa",
        "reputation",
        "transfer_listed",
        "loan_listed",
        "on_loan",
        "parent_club",
        "league",
        "contract_expiry",
        "contract_transfer_opts",
        "contract_option_years",
        "listed_reason",
    ):
        h[col] = tr(f"column_full.{col}")
    for a in ATTR_COLUMNS:
        h[a] = FULL_NAMES[a]
    for pc in PERSONALITY_COLS:
        h[pc] = pc[5:].replace("_", " ").title()
    return h


COL_HEADERS = _build_col_headers()
MENU_HEADERS = _build_menu_headers()


# ---------------------------------------------------------------------------
# Game state (set during scan)
# ---------------------------------------------------------------------------

GAME_YEAR = 0
GAME_DAY = 0
CURRENT_PROFILE = None

# Estimated value model coefficients
EST_POS_MULTIPLIERS = {
    "ST": 1.30,
    "AMC": 1.20,
    "AML": 1.15,
    "AMR": 1.15,
    "MC": 1.00,
    "ML": 0.95,
    "MR": 0.95,
    "DM": 0.90,
    "DC": 0.85,
    "DL": 0.80,
    "DR": 0.80,
    "WBL": 0.80,
    "WBR": 0.80,
    "GK": 0.65,
}

CONTRACT_STATUS_VALUES = (
    "any",
    "expiring_1y",
    "expiring_6m",
    "expiring_3m",
    "expiring_1m",
    "expired",
    "unattached",
    "non_contract",
    "youth",
    "amateur",
)


# ---------------------------------------------------------------------------
# Style sheets
# ---------------------------------------------------------------------------

SS_WIDGET = """
QWidget {
    background-color: #0d1117;
    color: #c9d1d9;
}
QPushButton {
    background-color: #21262d;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 4px;
    padding: 5px 14px;
    font-size: 12px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #30363d;
    border-color: #8b949e;
}
QPushButton:pressed {
    background-color: #161b22;
}
QPushButton#primary {
    background-color: #238636;
    border-color: #2ea043;
    color: #ffffff;
}
QPushButton#primary:hover {
    background-color: #2ea043;
    border-color: #3fb950;
}
QPushButton#primary:pressed {
    background-color: #238636;
}
QPushButton#secondary {
    background-color: #21262d;
    border-color: #30363d;
}
QLabel {
    color: #8b949e;
    font-size: 12px;
}
QLineEdit, QComboBox, QSpinBox {
    background-color: #161b22;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
    border-color: #1f6feb;
}
QComboBox::drop-down {
    border: none;
    padding-right: 6px;
}
QComboBox QAbstractItemView {
    background-color: #161b22;
    color: #c9d1d9;
    border: 1px solid #30363d;
}
QTabWidget::pane {
    border: 1px solid #21262d;
    background-color: #0d1117;
}
QTabBar::tab {
    background-color: #161b22;
    color: #8b949e;
    border: 1px solid #21262d;
    border-bottom: none;
    padding: 6px 16px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    font-size: 12px;
}
QTabBar::tab:selected {
    background-color: #0d1117;
    color: #f0f6fc;
    border-bottom: 2px solid #1f6feb;
}
QTabBar::tab:hover:!selected {
    background-color: #21262d;
    color: #c9d1d9;
}
QGroupBox {
    color: #f0f6fc;
    border: 1px solid #21262d;
    border-radius: 4px;
    margin-top: 12px;
    padding-top: 16px;
    font-size: 12px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QCheckBox {
    color: #c9d1d9;
    spacing: 6px;
    font-size: 12px;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #30363d;
    border-radius: 3px;
    background-color: #161b22;
}
QCheckBox::indicator:checked {
    background-color: #1f6feb;
    border-color: #1f6feb;
}
QProgressBar {
    background-color: #161b22;
    border: 1px solid #21262d;
    border-radius: 3px;
    text-align: center;
    color: #c9d1d9;
    font-size: 11px;
    height: 18px;
}
QProgressBar::chunk {
    background-color: #238636;
    border-radius: 2px;
}
QScrollArea {
    border: none;
}
QScrollBar:vertical {
    background: #0d1117;
    width: 10px;
    border: none;
}
QScrollBar::handle:vertical {
    background: #30363d;
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background: #484f58;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
"""

SS_TABLE = """
QTableView {
    background-color: #0d1117;
    color: #c9d1d9;
    gridline-color: #21262d;
    border: 1px solid #30363d;
    font-size: 12px;
    selection-background-color: #1f6feb33;
    selection-color: #f0f6fc;
}
QTableView::item:hover {
    background-color: #161b22;
}
QHeaderView::section {
    background-color: #161b22;
    color: #8b949e;
    border: 1px solid #21262d;
    padding: 4px 6px;
    font-weight: 600;
    font-size: 11px;
}
"""

SS_DIALOG = """
QDialog {
    background-color: #0d1117;
    color: #c9d1d9;
}
QDialogButtonBox QPushButton {
    min-width: 80px;
}
QMenu {
    background-color: #161b22;
    color: #c9d1d9;
    border: 1px solid #30363d;
    padding: 4px 0;
}
QMenu::item {
    padding: 4px 24px 4px 8px;
}
QMenu::item:selected {
    background-color: #1f6feb33;
}
QMenu::separator {
    height: 1px;
    background: #21262d;
    margin: 4px 8px;
}
"""

# Compact inputs for the attribute grid: the default QSpinBox padding makes
# 50+ editable rows overflow the dialog.
SS_ATTR_SPIN = """
QSpinBox#attrSpin, QSpinBox#abilitySpin {
    padding: 0px 3px;
    font-size: 11px;
    min-height: 0px;
    border: 1px solid #30363d;
    border-radius: 3px;
    background-color: #161b22;
}
QSpinBox#attrSpin:hover, QSpinBox#abilitySpin:hover {
    border-color: #484f58;
}
QSpinBox#attrSpin QLineEdit, QSpinBox#abilitySpin QLineEdit {
    padding: 0px;
    border: none;
    background: transparent;
}
QSpinBox#attrSpin::up-button, QSpinBox#attrSpin::down-button,
QSpinBox#abilitySpin::up-button, QSpinBox#abilitySpin::down-button {
    width: 0px;
    height: 0px;
    border: none;
}
"""


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def attr_color(val: int) -> QColor:
    if val >= 19:
        return QColor("#3fb950")
    if val >= 17:
        return QColor("#58a6ff")
    if val >= 14:
        return QColor("#8b949e")
    if val >= 10:
        return QColor("#d29922")
    if val >= 6:
        return QColor("#db6d28")
    return QColor("#f85149")


def attr_color_hex(val: int) -> str:
    if val >= 19:
        return "#3fb950"
    if val >= 17:
        return "#58a6ff"
    if val >= 14:
        return "#8b949e"
    if val >= 10:
        return "#d29922"
    if val >= 6:
        return "#db6d28"
    return "#f85149"


def _ca_pa_color(val: int) -> QColor:
    """Color for current/potential ability (0-200 scale)."""
    if val >= 170:
        return QColor("#3fb950")
    if val >= 140:
        return QColor("#58a6ff")
    if val >= 110:
        return QColor("#8b949e")
    if val >= 80:
        return QColor("#d29922")
    if val >= 50:
        return QColor("#db6d28")
    return QColor("#f85149")


def _player_age(player) -> int:
    if not player.birth_year or player.birth_year < 1900:
        return 0
    # Fallback to real-world date when in-game date scan is unavailable.
    year = GAME_YEAR
    day = GAME_DAY
    if year <= 0 or day <= 0:
        today = date.today()
        year = today.year
        day = today.timetuple().tm_yday

    age = year - player.birth_year
    if day and getattr(player, "birth_day", 0):
        if day < player.birth_day:
            age -= 1
    return max(0, age)


def _format_money(val) -> str:
    return format_eur_from_gbp(val)


def _format_fm_date(packed: int) -> str:
    if not packed:
        return ""
    year = (packed >> 16) & 0xFFFF
    day = packed & 0xFFFF
    if year == 0 or day == 0:
        return ""
    try:
        dt = date(year, 1, 1) + timedelta(days=day - 1)
        return dt.strftime("%d %b %Y")
    except (ValueError, OverflowError):
        return ""


def _current_game_date() -> date:
    year = GAME_YEAR
    day = GAME_DAY
    if year <= 0 or day <= 0:
        return date.today()
    try:
        return date(year, 1, 1) + timedelta(days=day - 1)
    except (ValueError, OverflowError):
        return date.today()


def _contract_days_left(player) -> int | None:
    expiry = getattr(player, "contract_expiry", 0) or 0
    if not expiry:
        return None
    year = (expiry >> 16) & 0xFFFF
    day = expiry & 0xFFFF
    if year <= 0 or day <= 0:
        return None
    try:
        exp_date = date(year, 1, 1) + timedelta(days=day - 1)
    except (ValueError, OverflowError):
        return None
    return (exp_date - _current_game_date()).days


def _matches_contract_status(player, status: str) -> bool:
    if not status or status == "any":
        return True

    club = (getattr(player, "club", "") or "").strip()
    wage = getattr(player, "wage", 0) or 0
    days_left = _contract_days_left(player)

    if status == "expiring_1y":
        return days_left is not None and 0 <= days_left <= 365
    if status == "expiring_6m":
        return days_left is not None and 0 <= days_left <= 183
    if status == "expiring_3m":
        return days_left is not None and 0 <= days_left <= 92
    if status == "expiring_1m":
        return days_left is not None and 0 <= days_left <= 31
    if status == "expired":
        return days_left is not None and days_left < 0
    if status == "unattached":
        return not club
    if status == "non_contract":
        return bool(club) and days_left is None and wage > 0
    if status == "youth":
        return (
            bool(club) and days_left is None and wage <= 0 and _player_age(player) <= 20
        )
    if status == "amateur":
        return (
            bool(club) and days_left is None and wage <= 0 and _player_age(player) > 20
        )
    return True


def _min_release_clause(player) -> int:
    vals = [
        getattr(player, "release_clause", 0) or 0,
        getattr(player, "release_clause_foreign", 0) or 0,
        getattr(player, "release_clause_domestic_higher", 0) or 0,
        getattr(player, "release_clause_domestic", 0) or 0,
        getattr(player, "release_clause_continental", 0) or 0,
        getattr(player, "release_clause_major_continental", 0) or 0,
    ]
    vals = [v for v in vals if v > 0]
    return min(vals) if vals else 0


def _estimated_player_value(player) -> int:
    ca = player.current_ability
    if ca <= 0:
        return 0

    pa = player.potential_ability or ca
    age = _player_age(player)
    rep = getattr(player, "current_reputation", 0) or player.reputation or 0
    wrep = getattr(player, "world_reputation", 0) or 0
    pos = getattr(player, "best_position", "") or ""

    base = 5.0 * (ca**3.39)

    if pa > ca and age < 28:
        growth = pa - ca
        youth = max(0, 28 - age) / 10.0
        base *= 1 + min(2.5, growth * 0.035 * youth)

    if 25 <= age <= 27:
        base *= 1.15
    elif 28 <= age <= 29:
        base *= 1.0
    elif age == 30:
        base *= 0.75
    elif age == 31:
        base *= 0.55
    elif age == 32:
        base *= 0.40
    elif age == 33:
        base *= 0.30
    elif age >= 34:
        base *= max(0.05, 0.20 - 0.05 * (age - 34))
    elif 22 <= age < 25:
        base *= 1.0
    elif 20 <= age < 22:
        base *= 0.80
    elif 18 <= age < 20:
        base *= 0.55
    elif age < 18:
        base *= 0.35

    effective_rep = max(wrep, rep * 0.5) if wrep > 0 else rep
    if effective_rep > 0:
        rn = min(effective_rep / 10000, 1.0)
        base *= 0.02 + 0.98 * (rn**1.5)
    else:
        base *= 0.02

    base *= EST_POS_MULTIPLIERS.get(pos, 1.0)

    # Formula was calibrated for EUR display values; convert back to the
    # internal GBP-like base so downstream formatting/export can apply a
    # single GBP->EUR conversion consistently.
    fx = get_gbp_to_eur_rate() or DEFAULT_GBP_TO_EUR_RATE
    if fx <= 0:
        fx = DEFAULT_GBP_TO_EUR_RATE
    return max(0, int(base / fx))


_COL_PLAYER_MAP = {
    "name": "display_name",
    "nationality": "nationality_display",
    "best_pos": "position_str",
    "ca": "current_ability",
    "pa": "potential_ability",
}


def _col_value(player, col_name: str):
    if col_name == "age":
        return _player_age(player)
    if col_name == "est_value":
        return _estimated_player_value(player)
    attr_name = _COL_PLAYER_MAP.get(col_name, col_name)
    return getattr(player, attr_name, None)


# ---------------------------------------------------------------------------
# Badge system
# ---------------------------------------------------------------------------

_BADGE_DEFS = [
    ("on_loan", tr("badge.on_loan"), QColor(210, 153, 34)),  # yellow
    ("transfer_listed", tr("badge.transfer_listed"), QColor(248, 81, 73)),  # red
    ("loan_listed", tr("badge.loan_listed"), QColor(63, 185, 80)),  # green
]


# ---------------------------------------------------------------------------
# NameBadgeDelegate
# ---------------------------------------------------------------------------


class NameBadgeDelegate(QStyledItemDelegate):
    """Paints coloured rounded-rect badge pills before player names."""

    def __init__(self, table_view: QTableView, model_ref=None, parent=None):
        super().__init__(parent or table_view)
        self._table = table_view
        self._model_ref = model_ref

    def set_model_ref(self, model_ref):
        self._model_ref = model_ref

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex
    ):
        painter.save()
        painter.setClipRect(option.rect)

        model = self._model_ref
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)

        if is_selected:
            painter.fillRect(option.rect, option.palette.highlight())
        else:
            if model is not None and model.is_hover_row(index.row()):
                bg = QColor("#161b22")
            else:
                bg = option.palette.base().color()
            painter.fillRect(option.rect, bg)
        player = None
        if model is not None:
            player = model.get_player(index.row())

        name = index.data(Qt.ItemDataRole.DisplayRole) or ""

        x = option.rect.left() + 4
        y_top = option.rect.top()
        h = option.rect.height()

        badge_font = QFont()
        badge_font.setPixelSize(9)
        badge_font.setBold(True)
        badge_height = 14
        badge_radius = 3.0
        badge_y = y_top + (h - badge_height) / 2

        if player is not None:
            for field, label, color in _BADGE_DEFS:
                if getattr(player, field, False):
                    fm = QFontMetrics(badge_font)
                    text_width = fm.horizontalAdvance(label)
                    badge_width = text_width + 8

                    badge_rect = QRectF(x, badge_y, badge_width, badge_height)
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    painter.setBrush(QBrush(color))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawRoundedRect(badge_rect, badge_radius, badge_radius)

                    painter.setFont(badge_font)
                    painter.setPen(QColor(0, 0, 0))
                    painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, label)

                    x += int(badge_width) + 3

        text_font = option.font if option.font else QFont()
        painter.setFont(text_font)

        if is_selected:
            painter.setPen(option.palette.highlightedText().color())
        else:
            painter.setPen(option.palette.text().color())

        text_rect = option.rect.adjusted(x - option.rect.left(), 0, -4, 0)
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            name,
        )
        painter.restore()

    def sizeHint(self, option, index):
        hint = super().sizeHint(option, index)
        hint.setHeight(max(hint.height(), 26))
        return hint


# ---------------------------------------------------------------------------
# PlayerTableModel
# ---------------------------------------------------------------------------


class PlayerTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_players: list = []
        self._view: list = []
        self._sort_col: int = -1
        self._sort_order: Qt.SortOrder = Qt.SortOrder.AscendingOrder
        self._hover_row: int = -1

    def set_all_players(self, players: list):
        self.beginResetModel()
        self._all_players = list(players)
        self._view = list(players)
        self._sort_col = -1
        self._hover_row = -1
        self.endResetModel()

    def filter(self, predicate=None):
        self.beginResetModel()
        if predicate is None:
            self._view = list(self._all_players)
        else:
            self._view = [p for p in self._all_players if predicate(p)]
        if self._sort_col >= 0:
            self._do_sort()
        self._hover_row = -1
        self.endResetModel()

    def refresh_row(self, row: int):
        """Repaint one row after its player was edited in place."""
        if not (0 <= row < len(self._view)):
            return
        last_col = max(0, self.columnCount() - 1)
        self.dataChanged.emit(self.index(row, 0), self.index(row, last_col))

    def refresh_all(self):
        """Repaint every visible row (players are shared between models)."""
        if not self._view:
            return
        last_col = max(0, self.columnCount() - 1)
        self.dataChanged.emit(
            self.index(0, 0), self.index(len(self._view) - 1, last_col)
        )

    def is_hover_row(self, row: int) -> bool:
        return row == self._hover_row

    def set_hover_row(self, row: int):
        new_row = row if 0 <= row < len(self._view) else -1
        if new_row == self._hover_row:
            return
        old_row = self._hover_row
        self._hover_row = new_row
        self._emit_hover_row_change(old_row)
        self._emit_hover_row_change(new_row)

    def clear_hover_row(self):
        self.set_hover_row(-1)

    def _emit_hover_row_change(self, row: int):
        if row < 0 or row >= len(self._view):
            return
        left = self.index(row, 0)
        right = self.index(row, len(TABLE_COLS) - 1)
        self.dataChanged.emit(left, right, [Qt.ItemDataRole.BackgroundRole])

    def get_player(self, row: int):
        if 0 <= row < len(self._view):
            return self._view[row]
        return None

    def get_view_players(self) -> list:
        return list(self._view)

    def get_all_players(self) -> list:
        return list(self._all_players)

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._view)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(TABLE_COLS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        if row < 0 or row >= len(self._view):
            return None

        col_name = TABLE_COLS[col]
        player = self._view[row]
        val = _col_value(player, col_name)

        if role == Qt.ItemDataRole.DisplayRole:
            if col_name in (
                "name",
                "club",
                "nationality",
                "best_pos",
                "parent_club",
                "league",
                "listed_reason",
            ):
                return str(val) if val else ""
            if col_name == "age":
                return str(val) if val else ""
            if col_name == "est_value":
                return _format_money(val)
            if col_name == "wage":
                return _format_money(val)
            if col_name in ("ca", "pa"):
                return str(val) if val else ""
            if col_name == "reputation":
                return str(val) if val else ""
            if col_name == "contract_expiry":
                return _format_fm_date(val) if val else ""
            if col_name in ("transfer_listed", "loan_listed", "on_loan"):
                return "Yes" if val else ""
            if col_name in ("contract_transfer_opts", "contract_option_years"):
                return str(val) if val else ""
            if col_name in ATTR_COLUMNS:
                return str(val) if val else ""
            if col_name in PERSONALITY_COLS:
                return str(val) if val else ""
            return str(val) if val is not None else ""

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col_name in (
                "age",
                "ca",
                "pa",
                "reputation",
                "est_value",
                "wage",
                "contract_transfer_opts",
                "contract_option_years",
            ):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            if col_name in ATTR_COLUMNS or col_name in PERSONALITY_COLS:
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        if role == Qt.ItemDataRole.BackgroundRole:
            if row == self._hover_row:
                return QColor("#161b22")

        if role == Qt.ItemDataRole.ForegroundRole:
            if col_name in ("ca", "pa"):
                v = int(val) if val else 0
                return _ca_pa_color(v)
            if col_name in ATTR_COLUMNS:
                v = int(val) if val else 0
                if v > 0:
                    return attr_color(v)
            if col_name in PERSONALITY_COLS:
                v = int(val) if val else 0
                if v > 0:
                    return attr_color(v)

        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
        ):
            if 0 <= section < len(TABLE_COLS):
                return COL_HEADERS.get(TABLE_COLS[section], TABLE_COLS[section])
        return None

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder):
        self.beginResetModel()
        self._sort_col = column
        self._sort_order = order
        self._do_sort()
        self.endResetModel()

    def _do_sort(self):
        if self._sort_col < 0 or self._sort_col >= len(TABLE_COLS):
            return
        col_name = TABLE_COLS[self._sort_col]
        reverse = self._sort_order == Qt.SortOrder.DescendingOrder

        def sort_key(p):
            v = _col_value(p, col_name)
            if v is None:
                return (0, "")
            if isinstance(v, str):
                return (1, v.lower())
            if isinstance(v, bool):
                return (1 if v else 0, "")
            return (v, "")

        self._view.sort(key=sort_key, reverse=reverse)


# ---------------------------------------------------------------------------
# ScanWorker
# ---------------------------------------------------------------------------


class ScanWorker(QThread):
    progress = pyqtSignal(int, int, str)
    quick_ready = pyqtSignal(dict)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def run(self):
        reader = None
        try:
            self.progress.emit(0, 100, tr("msg.finding_process"))
            proc = find_fm_process()
            if proc is None:
                self.error.emit(tr("msg.no_process"))
                return

            self.progress.emit(10, 100, tr("msg.opening_memory"))
            reader = MemoryReader(proc.pid)
            reader.open()

            self.progress.emit(20, 100, tr("msg.getting_regions"))
            regions = get_memory_regions(proc.pid)

            self.progress.emit(30, 100, tr("msg.scanning_data"))
            scanner = GameScanner(reader, regions, profiles=get_profiles())
            ok = scanner.scan_all()
            if not ok:
                detail = scanner.last_error or tr("msg.scan_failed")
                self.error.emit(tr("msg.scan_failed_detail", detail=detail))
                reader.close()
                return

            profile = scanner.profile
            global GAME_YEAR, GAME_DAY, CURRENT_PROFILE
            CURRENT_PROFILE = profile
            GAME_YEAR = scanner.pointers.game_date_year
            GAME_DAY = scanner.pointers.game_date_day
            if GAME_YEAR <= 0 or GAME_DAY <= 0:
                today = date.today()
                GAME_YEAR = today.year
                GAME_DAY = today.timetuple().tm_yday

            self.progress.emit(50, 100, tr("msg.reading_players"))
            player_reader = PlayerReader(
                reader,
                profile.struct,
                attribute_byte_offsets=profile.attribute_byte_offsets,
            )
            player_reader.PLAYER_VTABLES = set(scanner.player_vtables)
            person_ptrs = scanner.get_person_pointers()
            players = player_reader.read_all_players(person_ptrs)
            quick_my_club = scanner.pointers.human_club_name or ""
            # Tier 1: publish player data early; clubs/enrichment continue.
            self.quick_ready.emit(
                {
                    "players": players,
                    "my_club": quick_my_club,
                    "game_version": profile.label,
                }
            )

            self.progress.emit(70, 100, tr("msg.reading_clubs"))
            club_reader = ClubReader(reader, scanner.pointers.dbt_root, profile.club)
            clubs = club_reader.read_all_clubs()
            my_club_name = (
                scanner.pointers.human_club_name
                or scanner.resolve_human_manager_club(profile)
                or ""
            )

            self.progress.emit(85, 100, tr("msg.enriching"))
            enrich_clubs_with_players(
                clubs, players, GAME_YEAR, value_fn=_estimated_player_value
            )

            reader.close()
            reader = None

            self.progress.emit(100, 100, tr("msg.done"))
            self.finished.emit(
                {
                    "players": players,
                    "clubs": clubs,
                    "my_club": my_club_name,
                    "game_version": profile.label,
                }
            )

        except Exception as e:
            logger.exception("Scan failed")
            self.error.emit(str(e))
        finally:
            if reader is not None:
                try:
                    reader.close()
                except OSError:
                    pass


# ---------------------------------------------------------------------------
# PositionFilterWidget
# ---------------------------------------------------------------------------

_POS_COORDS = {
    "ST": (0.50, 0.10),
    "AML": (0.24, 0.26),
    "AMC": (0.50, 0.26),
    "AMR": (0.76, 0.26),
    "ML": (0.24, 0.42),
    "MC": (0.50, 0.42),
    "MR": (0.76, 0.42),
    "WBL": (0.24, 0.58),
    "DM": (0.50, 0.58),
    "WBR": (0.76, 0.58),
    "DL": (0.24, 0.74),
    "DC": (0.50, 0.74),
    "DR": (0.76, 0.74),
    "GK": (0.50, 0.90),
}

_POS_CYCLE = [0, 5, 10, 15, 20]
_DOT_RADIUS = 16


class PositionFilterWidget(QWidget):
    """Interactive pitch diagram with clickable position dots."""

    values_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(280, 380)
        self._values: dict[str, int] = {p: 0 for p in _POS_COORDS}
        self.setMouseTracking(True)
        self._hover_pos: Optional[str] = None

    def get_values(self) -> dict[str, int]:
        return {k: v for k, v in self._values.items() if v > 0}

    def set_values(self, values: dict[str, int]):
        self._values = {p: 0 for p in _POS_COORDS}
        for k, v in values.items():
            if k in self._values:
                self._values[k] = v
        self.update()

    def reset(self):
        self._values = {p: 0 for p in _POS_COORDS}
        self.update()
        self.values_changed.emit()

    @staticmethod
    def _draw_pitch(painter: QPainter, w: int, h: int):
        painter.fillRect(0, 0, w, h, QColor("#1e4d2b"))

        line_pen = QPen(QColor(255, 255, 255, 110))
        line_pen.setWidthF(1.5)
        painter.setPen(line_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        m = 12
        pw, ph = w - 2 * m, h - 2 * m
        painter.drawRect(m, m, pw, ph)

        mid_y = m + ph // 2
        painter.drawLine(m, mid_y, m + pw, mid_y)

        cr = min(pw, ph) * 0.07
        painter.drawEllipse(QRectF(w / 2 - cr, mid_y - cr, cr * 2, cr * 2))

        pa_w = int(pw * 0.52)
        pa_h = int(ph * 0.14)
        pa_x = m + (pw - pa_w) // 2
        painter.drawRect(pa_x, m, pa_w, pa_h)
        painter.drawRect(pa_x, m + ph - pa_h, pa_w, pa_h)

        ga_w = int(pw * 0.24)
        ga_h = int(ph * 0.05)
        ga_x = m + (pw - ga_w) // 2
        painter.drawRect(ga_x, m, ga_w, ga_h)
        painter.drawRect(ga_x, m + ph - ga_h, ga_w, ga_h)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()

        PositionFilterWidget._draw_pitch(painter, w, h)

        label_font = QFont("sans-serif", 0)
        label_font.setPixelSize(max(9, _DOT_RADIUS - 4))
        label_font.setBold(True)

        r = _DOT_RADIUS
        for pos_name, (fx, fy) in _POS_COORDS.items():
            cx = int(fx * w)
            cy = int(fy * h)
            val = self._values.get(pos_name, 0)

            if val <= 1:
                fill = QColor("#4b5563")
            elif val <= 4:
                fill = QColor("#dc2626")
            elif val <= 9:
                fill = QColor("#ea580c")
            elif val <= 14:
                fill = QColor("#eab308")
            elif val <= 18:
                fill = QColor("#16a34a")
            else:
                fill = QColor("#4ade80")

            is_hover = self._hover_pos == pos_name
            if is_hover:
                fill = fill.lighter(135)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(fill))
            painter.drawEllipse(cx - r, cy - r, r * 2, r * 2)

            painter.setPen(QColor("#ffffff"))
            painter.setFont(label_font)
            painter.drawText(
                QRectF(cx - r, cy - r, r * 2, r * 2),
                Qt.AlignmentFlag.AlignCenter,
                pos_name,
            )

        painter.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = self._hit_test(event.position().x(), event.position().y())
        if pos:
            cur = self._values.get(pos, 0)
            try:
                idx = _POS_CYCLE.index(cur)
                next_val = _POS_CYCLE[(idx + 1) % len(_POS_CYCLE)]
            except ValueError:
                next_val = _POS_CYCLE[0]
            self._values[pos] = next_val
            self.update()
            self.values_changed.emit()

    def mouseMoveEvent(self, event):
        old_hover = self._hover_pos
        self._hover_pos = self._hit_test(event.position().x(), event.position().y())
        if self._hover_pos != old_hover:
            self.update()

    def leaveEvent(self, event):
        self._hover_pos = None
        self.update()

    def _hit_test(self, mx: float, my: float) -> Optional[str]:
        w = self.width()
        h = self.height()
        for pos_name, (fx, fy) in _POS_COORDS.items():
            cx = fx * w
            cy = fy * h
            dist = math.hypot(mx - cx, my - cy)
            if dist <= _DOT_RADIUS + 4:
                return pos_name
        return None


class _PlayerPositionPitch(QWidget):
    """Pitch diagram showing a player's position ratings."""

    def __init__(self, positions: dict[str, int], parent=None):
        super().__init__(parent)
        self._positions = positions

    def set_value(self, pos_name: str, value: int):
        """Update one rating and repaint (used for live edit preview)."""
        self._positions[pos_name] = value
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()

        PositionFilterWidget._draw_pitch(painter, w, h)

        label_font = QFont("sans-serif", 0)
        label_font.setPixelSize(max(9, _DOT_RADIUS - 4))
        label_font.setBold(True)

        r = _DOT_RADIUS
        for pos_name, (fx, fy) in _POS_COORDS.items():
            cx = int(fx * w)
            cy = int(fy * h)
            val = self._positions.get(pos_name, 0)

            if val <= 1:
                fill = QColor("#4b5563")
            elif val <= 4:
                fill = QColor("#dc2626")
            elif val <= 9:
                fill = QColor("#ea580c")
            elif val <= 14:
                fill = QColor("#eab308")
            elif val <= 18:
                fill = QColor("#16a34a")
            else:
                fill = QColor("#4ade80")

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(fill))
            painter.drawEllipse(cx - r, cy - r, r * 2, r * 2)

            painter.setPen(QColor("#ffffff"))
            painter.setFont(label_font)
            painter.drawText(
                QRectF(cx - r, cy - r, r * 2, r * 2),
                Qt.AlignmentFlag.AlignCenter,
                pos_name,
            )

        painter.end()


class HorizontalTextTabBar(QTabBar):
    """Left-side tab bar with horizontal labels."""

    def tabSizeHint(self, index: int) -> QSize:
        size = super().tabSizeHint(index)
        size.transpose()
        size.setWidth(max(size.width(), 110))
        size.setHeight(min(size.height(), 28))
        return size

    def paintEvent(self, _event):
        painter = QStylePainter(self)
        opt = QStyleOptionTab()

        for i in range(self.count()):
            self.initStyleOption(opt, i)
            painter.drawControl(QStyle.ControlElement.CE_TabBarTabShape, opt)
            painter.save()
            text_rect = self.tabRect(i).adjusted(8, 0, -8, 0)
            if i == self.currentIndex():
                painter.setPen(QColor("#f0f6fc"))
            else:
                painter.setPen(QColor("#8b949e"))
            painter.drawText(
                text_rect,
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter),
                self.tabText(i),
            )
            painter.restore()


# ---------------------------------------------------------------------------
# SearchDialog
# ---------------------------------------------------------------------------


class SearchDialog(QDialog):
    """Filter dialog with tabs for all attribute categories."""

    def __init__(
        self, filter_data: dict, current_filters: dict | None = None, parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle(tr("filter.title"))
        self.setMinimumSize(700, 600)
        self.setStyleSheet(SS_WIDGET + SS_DIALOG)

        self._filter_data = filter_data
        self._current = current_filters or {}
        self._attr_spins: dict[str, tuple[QSpinBox, QSpinBox]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        self._tabs = QTabWidget()
        self._tabs.setTabBar(HorizontalTextTabBar())
        self._tabs.setTabPosition(QTabWidget.TabPosition.West)
        layout.addWidget(self._tabs)

        self._build_general_tab()
        self._build_contract_tab()
        self._build_attr_tab("Technical", ATTR_OFFSETS.TECHNICAL_FIELDS)
        self._build_attr_tab("Mental", ATTR_OFFSETS.MENTAL_FIELDS)
        self._build_attr_tab("Physical", ATTR_OFFSETS.PHYSICAL_FIELDS)
        self._build_attr_tab("Goalkeeping", ATTR_OFFSETS.GOALKEEPER_FIELDS)
        self._build_attr_tab(
            "Personality",
            PERSONALITY_COLS,
            label_fn=lambda c: c[5:].replace("_", " ").title(),
        )
        self._build_attr_tab("Hidden", ATTR_OFFSETS.HIDDEN_FIELDS)
        self._build_traits_tab()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Reset
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        clear_btn = buttons.button(QDialogButtonBox.StandardButton.Reset)
        clear_btn.setText(tr("button.clear_all"))
        clear_btn.clicked.connect(self._clear_all)
        layout.addWidget(buttons)

        self._restore_from_current()

    # -- General tab -------------------------------------------------------

    def _build_general_tab(self):
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(8, 8, 8, 8)

        name_row = QHBoxLayout()
        name_label = QLabel(tr("filter.name"))
        name_label.setStyleSheet("color: #f0f6fc; font-size: 12px; font-weight: 600;")
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText(tr("filter.name_placeholder"))
        name_row.addWidget(name_label)
        name_row.addWidget(self._name_edit, 1)
        outer.addLayout(name_row)

        top_row = QHBoxLayout()

        # Nationality filter (player's own nationality)
        nat_group = QGroupBox(tr("group.nationality"))
        nat_layout = QFormLayout(nat_group)
        nat_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )

        self._nat_continent_combo = QComboBox()
        self._configure_combo_popup(self._nat_continent_combo)
        self._nat_continent_combo.addItem(tr("filter.any"))
        for c in self._filter_data.get("nat_continents", []):
            self._nat_continent_combo.addItem(c)
        self._nat_continent_combo.currentTextChanged.connect(
            self._on_nat_continent_changed
        )
        nat_layout.addRow(tr("filter.continent"), self._nat_continent_combo)

        self._nat_nation_combo = QComboBox()
        self._configure_combo_popup(self._nat_nation_combo)
        self._nat_nation_combo.addItem(tr("filter.any"))
        nat_layout.addRow(tr("filter.nation"), self._nat_nation_combo)

        top_row.addWidget(nat_group)

        # Club location filter (league geography)
        loc_group = QGroupBox(tr("group.club_location"))
        loc_layout = QFormLayout(loc_group)
        loc_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )

        self._continent_combo = QComboBox()
        self._configure_combo_popup(self._continent_combo)
        self._continent_combo.addItem(tr("filter.any"))
        for c in self._filter_data.get("club_continents", []):
            self._continent_combo.addItem(c)
        self._continent_combo.currentTextChanged.connect(self._on_continent_changed)
        loc_layout.addRow(tr("filter.continent"), self._continent_combo)

        self._nation_combo = QComboBox()
        self._configure_combo_popup(self._nation_combo)
        self._nation_combo.addItem(tr("filter.any"))
        self._nation_combo.currentTextChanged.connect(self._on_nation_changed)
        loc_layout.addRow(tr("filter.nation"), self._nation_combo)

        self._league_combo = QComboBox()
        self._configure_combo_popup(self._league_combo)
        self._league_combo.addItem(tr("filter.any"))
        self._league_combo.currentTextChanged.connect(self._on_league_changed)
        loc_layout.addRow(tr("filter.league"), self._league_combo)

        self._club_combo = QComboBox()
        self._configure_combo_popup(self._club_combo)
        self._club_combo.addItem(tr("filter.any"))
        loc_layout.addRow(tr("filter.club"), self._club_combo)

        top_row.addWidget(loc_group)
        outer.addLayout(top_row)

        # Position filter + ranges side by side
        mid_layout = QHBoxLayout()

        pos_group = QGroupBox(tr("group.positions"))
        pos_inner = QVBoxLayout(pos_group)
        self._pos_widget = PositionFilterWidget()
        pos_inner.addWidget(self._pos_widget)
        mid_layout.addWidget(pos_group)

        range_group = QGroupBox(tr("group.ranges"))
        range_layout = QFormLayout(range_group)
        range_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )

        self._age_min = self._spin(15, 50, 0)
        self._age_max = self._spin(15, 50, 0)
        range_layout.addRow(tr("filter.age_min"), self._age_min)
        range_layout.addRow(tr("filter.age_max"), self._age_max)

        self._ca_min = self._spin(0, 200, 0)
        self._ca_max = self._spin(0, 200, 0)
        range_layout.addRow(tr("filter.ca_min"), self._ca_min)
        range_layout.addRow(tr("filter.ca_max"), self._ca_max)

        self._pa_min = self._spin(0, 200, 0)
        self._pa_max = self._spin(0, 200, 0)
        range_layout.addRow(tr("filter.pa_min"), self._pa_min)
        range_layout.addRow(tr("filter.pa_max"), self._pa_max)

        self._rep_min = self._spin(0, 10000, 0, step=100)
        self._rep_max = self._spin(0, 10000, 0, step=100)
        range_layout.addRow(tr("filter.rep_min"), self._rep_min)
        range_layout.addRow(tr("filter.rep_max"), self._rep_max)

        self._est_value_min = self._spin(0, 1_000_000_000, 0, step=10_000)
        self._est_value_max = self._spin(0, 1_000_000_000, 0, step=10_000)
        range_layout.addRow(tr("filter.est_value_min"), self._est_value_min)
        range_layout.addRow(tr("filter.est_value_max"), self._est_value_max)

        mid_layout.addWidget(range_group)
        outer.addLayout(mid_layout)
        outer.addStretch()

        self._tabs.addTab(tab, "General")

    def _build_contract_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)

        group = QGroupBox(tr("menu.contract_status"))
        form = QFormLayout(group)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self._contract_status_combo = QComboBox()
        self._configure_combo_popup(self._contract_status_combo)
        for value in CONTRACT_STATUS_VALUES:
            self._contract_status_combo.addItem(
                tr(f"filter.contract_status_option.{value}"), value
            )
        form.addRow(tr("filter.contract_status"), self._contract_status_combo)

        self._wage_min = self._spin(0, 10_000_000, 0, step=1000)
        self._wage_max = self._spin(0, 10_000_000, 0, step=1000)
        form.addRow(tr("filter.wage_min"), self._wage_min)
        form.addRow(tr("filter.wage_max"), self._wage_max)

        self._release_clause_min = self._spin(0, 1_000_000_000, 0, step=10_000)
        self._release_clause_max = self._spin(0, 1_000_000_000, 0, step=10_000)
        form.addRow(tr("filter.release_clause_min"), self._release_clause_min)
        form.addRow(tr("filter.release_clause_max"), self._release_clause_max)

        layout.addWidget(group)
        layout.addStretch()
        self._tabs.addTab(tab, "Contract")

    def _on_nat_continent_changed(self, text: str):
        self._nat_nation_combo.blockSignals(True)
        self._nat_nation_combo.clear()
        self._nat_nation_combo.addItem(tr("filter.any"))
        if text and text != tr("filter.any"):
            nations = self._filter_data.get("nat_nations", {}).get(text, [])
            for n in nations:
                self._nat_nation_combo.addItem(n)
        self._nat_nation_combo.blockSignals(False)

    def _on_continent_changed(self, text: str):
        self._nation_combo.blockSignals(True)
        self._nation_combo.clear()
        self._nation_combo.addItem(tr("filter.any"))
        if text and text != tr("filter.any"):
            nations = self._filter_data.get("club_nations", {}).get(text, [])
            for n in nations:
                self._nation_combo.addItem(n)
        self._nation_combo.blockSignals(False)
        self._on_nation_changed(self._nation_combo.currentText())

    def _on_nation_changed(self, text: str):
        self._league_combo.blockSignals(True)
        self._league_combo.clear()
        self._league_combo.addItem(tr("filter.any"))
        if text and text != tr("filter.any"):
            leagues = self._filter_data.get("leagues", {}).get(text, [])
            for league_name, rep in leagues:
                self._league_combo.addItem(
                    f"{league_name} ({rep})" if rep else league_name
                )
        self._league_combo.blockSignals(False)
        self._on_league_changed(self._league_combo.currentText())

    def _on_league_changed(self, text: str):
        self._club_combo.blockSignals(True)
        self._club_combo.clear()
        self._club_combo.addItem(tr("filter.any"))
        if text and text != tr("filter.any"):
            league_name = text.rsplit(" (", 1)[0]
            clubs = self._filter_data.get("clubs", {}).get(league_name, [])
            for c in sorted(clubs):
                self._club_combo.addItem(c)
        self._club_combo.blockSignals(False)

    # -- Traits tab --------------------------------------------------------

    def _build_traits_tab(self):
        from fm_scout.player import PLAYER_TRAIT_MAP

        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(2)

        self._trait_checks: dict[str, QCheckBox] = {}
        for _, _, name in PLAYER_TRAIT_MAP:
            cb = QCheckBox(name)
            cb.setStyleSheet("color: #c9d1d9; font-size: 11px;")
            lay.addWidget(cb)
            self._trait_checks[name] = cb

        lay.addStretch()
        scroll.setWidget(content)
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(scroll)
        self._tabs.addTab(tab, "Traits")

    # -- Attribute tabs ----------------------------------------------------

    def _build_attr_tab(self, title: str, fields, label_fn=None):
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        grid = QGridLayout(content)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop)

        hdr_font = QFont()
        hdr_font.setBold(True)
        for col_offset in (0, 4):
            lbl_attr = QLabel("Attribute")
            lbl_attr.setFont(hdr_font)
            lbl_attr.setStyleSheet("color: #8b949e;")
            grid.addWidget(lbl_attr, 0, col_offset)
            lbl_min = QLabel("Min")
            lbl_min.setFont(hdr_font)
            lbl_min.setStyleSheet("color: #8b949e;")
            grid.addWidget(lbl_min, 0, col_offset + 1)
            lbl_max = QLabel("Max")
            lbl_max.setFont(hdr_font)
            lbl_max.setStyleSheet("color: #8b949e;")
            grid.addWidget(lbl_max, 0, col_offset + 2)

        half = (len(fields) + 1) // 2
        for i, field in enumerate(fields):
            if label_fn:
                display = label_fn(field)
            else:
                display = FULL_NAMES.get(field, field.replace("_", " ").title())
            col_offset = 0 if i < half else 4
            row = (i % half) + 1

            lbl = QLabel(display)
            lbl.setStyleSheet("color: #c9d1d9; font-size: 12px;")
            grid.addWidget(lbl, row, col_offset)

            spin_min = self._spin(0, 20, 0)
            spin_min.setMaximumWidth(55)
            grid.addWidget(spin_min, row, col_offset + 1)

            spin_max = self._spin(0, 20, 0)
            spin_max.setMaximumWidth(55)
            grid.addWidget(spin_max, row, col_offset + 2)

            self._attr_spins[field] = (spin_min, spin_max)

        grid.setColumnStretch(3, 1)
        grid.setColumnStretch(7, 1)
        # Keep attribute rows packed at the top; spare space goes below.
        grid.setRowStretch(half + 2, 1)

        scroll.setWidget(content)
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(scroll)
        self._tabs.addTab(tab, title)

    # -- Helpers -----------------------------------------------------------

    @staticmethod
    def _spin(lo: int, hi: int, default: int, step: int = 1) -> QSpinBox:
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(default)
        s.setSingleStep(step)
        s.setSpecialValueText("-")
        return s

    @staticmethod
    def _configure_combo_popup(combo: QComboBox):
        """Ensure popup rows highlight on hover on all Qt styles."""
        lv = QListView(combo)
        lv.setMouseTracking(True)
        combo.setView(lv)

        pal = lv.palette()
        pal.setColor(
            QPalette.ColorGroup.Active, QPalette.ColorRole.Highlight, QColor("#2b6cb0")
        )
        pal.setColor(
            QPalette.ColorGroup.Active,
            QPalette.ColorRole.HighlightedText,
            QColor("#f0f6fc"),
        )
        pal.setColor(
            QPalette.ColorGroup.Inactive,
            QPalette.ColorRole.Highlight,
            QColor("#2b6cb0"),
        )
        pal.setColor(
            QPalette.ColorGroup.Inactive,
            QPalette.ColorRole.HighlightedText,
            QColor("#f0f6fc"),
        )
        pal.setColor(
            QPalette.ColorGroup.Active, QPalette.ColorRole.Base, QColor("#161b22")
        )
        pal.setColor(
            QPalette.ColorGroup.Inactive, QPalette.ColorRole.Base, QColor("#161b22")
        )
        pal.setColor(
            QPalette.ColorGroup.Active, QPalette.ColorRole.Text, QColor("#c9d1d9")
        )
        pal.setColor(
            QPalette.ColorGroup.Inactive, QPalette.ColorRole.Text, QColor("#c9d1d9")
        )
        lv.setPalette(pal)

        def _select_on_hover(idx: QModelIndex):
            lv.selectionModel().setCurrentIndex(
                idx, QItemSelectionModel.SelectionFlag.ClearAndSelect
            )

        lv._hover_cb = _select_on_hover
        lv.entered.connect(lv._hover_cb)

    # -- Clear all ---------------------------------------------------------

    def _clear_all(self):
        self._name_edit.clear()
        self._nat_continent_combo.setCurrentIndex(0)
        self._nat_nation_combo.setCurrentIndex(0)
        self._continent_combo.setCurrentIndex(0)
        self._nation_combo.setCurrentIndex(0)
        self._league_combo.setCurrentIndex(0)
        self._club_combo.setCurrentIndex(0)
        self._pos_widget.reset()
        self._age_min.setValue(self._age_min.minimum())
        self._age_max.setValue(self._age_max.minimum())
        self._ca_min.setValue(0)
        self._ca_max.setValue(0)
        self._pa_min.setValue(0)
        self._pa_max.setValue(0)
        self._rep_min.setValue(0)
        self._rep_max.setValue(0)
        self._wage_min.setValue(0)
        self._wage_max.setValue(0)
        self._est_value_min.setValue(0)
        self._est_value_max.setValue(0)
        self._release_clause_min.setValue(0)
        self._release_clause_max.setValue(0)
        self._contract_status_combo.setCurrentIndex(0)
        for smin, smax in self._attr_spins.values():
            smin.setValue(0)
            smax.setValue(0)
        for cb in self._trait_checks.values():
            cb.setChecked(False)

    # -- Restore / collect -------------------------------------------------

    def _restore_from_current(self):
        c = self._current
        if not c:
            return
        if c.get("name"):
            self._name_edit.setText(c["name"])
        if c.get("nat_continent"):
            idx = self._nat_continent_combo.findText(c["nat_continent"])
            if idx >= 0:
                self._nat_continent_combo.setCurrentIndex(idx)
        if c.get("nationality"):
            idx = self._nat_nation_combo.findText(c["nationality"])
            if idx >= 0:
                self._nat_nation_combo.setCurrentIndex(idx)
        if c.get("club_continent"):
            idx = self._continent_combo.findText(c["club_continent"])
            if idx >= 0:
                self._continent_combo.setCurrentIndex(idx)
        if c.get("club_nation"):
            idx = self._nation_combo.findText(c["club_nation"])
            if idx >= 0:
                self._nation_combo.setCurrentIndex(idx)
        if c.get("league_display"):
            idx = self._league_combo.findText(c["league_display"])
            if idx >= 0:
                self._league_combo.setCurrentIndex(idx)
        if c.get("club"):
            idx = self._club_combo.findText(c["club"])
            if idx >= 0:
                self._club_combo.setCurrentIndex(idx)

        self._age_min.setValue(c.get("age_min", 0))
        self._age_max.setValue(c.get("age_max", 0))
        self._ca_min.setValue(c.get("ca_min", 0))
        self._ca_max.setValue(c.get("ca_max", 0))
        self._pa_min.setValue(c.get("pa_min", 0))
        self._pa_max.setValue(c.get("pa_max", 0))
        self._rep_min.setValue(c.get("rep_min", 0))
        self._rep_max.setValue(c.get("rep_max", 0))
        self._wage_min.setValue(c.get("wage_min", 0))
        self._wage_max.setValue(c.get("wage_max", 0))
        self._est_value_min.setValue(c.get("est_value_min", 0))
        self._est_value_max.setValue(c.get("est_value_max", 0))
        self._release_clause_min.setValue(c.get("release_clause_min", 0))
        self._release_clause_max.setValue(c.get("release_clause_max", 0))
        contract_status = c.get("contract_status", "any")
        idx = self._contract_status_combo.findData(contract_status)
        self._contract_status_combo.setCurrentIndex(idx if idx >= 0 else 0)

        self._pos_widget.set_values(c.get("positions", {}))

        for attr, (smin, smax) in self._attr_spins.items():
            bounds = c.get("attrs", {}).get(attr)
            if bounds:
                smin.setValue(bounds[0])
                smax.setValue(bounds[1])

        for trait_name in c.get("traits", []):
            cb = self._trait_checks.get(trait_name)
            if cb:
                cb.setChecked(True)

    def get_filters(self) -> dict:
        f: dict = {}

        name = self._name_edit.text().strip()
        if name:
            f["name"] = name

        nat_cont = self._nat_continent_combo.currentText()
        if nat_cont and nat_cont != tr("filter.any"):
            f["nat_continent"] = nat_cont

        nationality = self._nat_nation_combo.currentText()
        if nationality and nationality != tr("filter.any"):
            f["nationality"] = nationality

        continent = self._continent_combo.currentText()
        if continent and continent != tr("filter.any"):
            f["club_continent"] = continent

        nation = self._nation_combo.currentText()
        if nation and nation != tr("filter.any"):
            f["club_nation"] = nation

        league_text = self._league_combo.currentText()
        if league_text and league_text != tr("filter.any"):
            f["league_display"] = league_text
            f["league"] = league_text.rsplit(" (", 1)[0]

        club = self._club_combo.currentText()
        if club and club != tr("filter.any"):
            f["club"] = club

        if self._age_min.value() > self._age_min.minimum():
            f["age_min"] = self._age_min.value()
        if self._age_max.value() > self._age_max.minimum():
            f["age_max"] = self._age_max.value()
        if self._ca_min.value() > 0:
            f["ca_min"] = self._ca_min.value()
        if self._ca_max.value() > 0:
            f["ca_max"] = self._ca_max.value()
        if self._pa_min.value() > 0:
            f["pa_min"] = self._pa_min.value()
        if self._pa_max.value() > 0:
            f["pa_max"] = self._pa_max.value()
        if self._rep_min.value() > 0:
            f["rep_min"] = self._rep_min.value()
        if self._rep_max.value() > 0:
            f["rep_max"] = self._rep_max.value()
        if self._wage_min.value() > 0:
            f["wage_min"] = self._wage_min.value()
        if self._wage_max.value() > 0:
            f["wage_max"] = self._wage_max.value()
        if self._est_value_min.value() > 0:
            f["est_value_min"] = self._est_value_min.value()
        if self._est_value_max.value() > 0:
            f["est_value_max"] = self._est_value_max.value()
        if self._release_clause_min.value() > 0:
            f["release_clause_min"] = self._release_clause_min.value()
        if self._release_clause_max.value() > 0:
            f["release_clause_max"] = self._release_clause_max.value()
        contract_status = self._contract_status_combo.currentData()
        if contract_status and contract_status != "any":
            f["contract_status"] = contract_status

        pos = self._pos_widget.get_values()
        if pos:
            f["positions"] = pos

        attrs: dict[str, tuple[int, int]] = {}
        for attr, (smin, smax) in self._attr_spins.items():
            lo = smin.value()
            hi = smax.value()
            if lo > 0 or hi > 0:
                attrs[attr] = (lo, hi)
        if attrs:
            f["attrs"] = attrs

        selected_traits = [
            name for name, cb in self._trait_checks.items() if cb.isChecked()
        ]
        if selected_traits:
            f["traits"] = selected_traits

        return f


# ---------------------------------------------------------------------------
# PlayerDetailDialog
# ---------------------------------------------------------------------------


class _AttrSpinBox(QSpinBox):
    """Compact spin box for the attribute grid.

    Drops the step arrows to save width and only responds to the wheel
    when focused, so scrolling the tab does not silently change values.
    """

    def __init__(self, minimum: int, maximum: int, value: int, width: int):
        super().__init__()
        self.setObjectName("attrSpin")
        # Some Qt stylesheet versions give NoButtons a one-pixel edit field.
        # Keep the controls enabled internally and hide them in SS_ATTR_SPIN.
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.UpDownArrows)
        self.setRange(minimum, maximum)
        self.setValue(value)
        self._compact_width = width
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def sizeHint(self):
        self.ensurePolished()
        metrics = self.lineEdit().fontMetrics()
        text_width = max(
            metrics.horizontalAdvance(self.textFromValue(self.minimum())),
            metrics.horizontalAdvance(self.textFromValue(self.maximum())),
            metrics.horizontalAdvance(self.specialValueText()),
        )
        return QSize(
            max(self._compact_width, text_width + 8), max(20, metrics.height() + 4)
        )

    def minimumSizeHint(self):
        return self.sizeHint()

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class PlayerDetailDialog(QDialog):
    """Full player information dialog shown on double-click."""

    def __init__(self, player, parent=None):
        super().__init__(parent)
        self.setWindowTitle(
            getattr(player, "display_name", "") or tr("player.title_fallback")
        )
        self.setMinimumSize(900, 700)
        self.resize(980, 820)
        self.setStyleSheet(SS_WIDGET + SS_DIALOG + SS_ATTR_SPIN)

        self._player = player
        self._attr_spins: dict[str, QSpinBox] = {}
        self._pos_spins: dict[str, QSpinBox] = {}
        self._pers_spins: dict[str, QSpinBox] = {}
        self._ca_spin: QSpinBox | None = None
        self._pa_spin: QSpinBox | None = None
        self._position_pitch: _PlayerPositionPitch | None = None
        self.player_edited = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        layout.addWidget(self._build_header(player))
        self._stats_row = self._build_stats_row(player)
        layout.addWidget(self._stats_row)

        contract_w = self._build_contract_info(player)
        if contract_w:
            layout.addWidget(contract_w)

        tabs = QTabWidget()
        tabs.addTab(self._build_attributes_tab(player), "Attributes")
        tabs.addTab(self._build_positions_tab(player), "Positions")
        tabs.addTab(self._build_contract_tab(player), "Contract")
        tabs.addTab(self._build_traits_tab(player), "Traits")
        layout.addWidget(tabs, 1)

        layout.addWidget(self._build_edit_bar())

    def _build_header(self, player) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 8)

        name_lbl = QLabel(getattr(player, "display_name", ""))
        name_font = QFont()
        name_font.setPointSize(18)
        name_font.setBold(True)
        name_lbl.setFont(name_font)
        name_lbl.setStyleSheet("color: #f0f6fc;")
        lay.addWidget(name_lbl)

        parts = []
        if player.club:
            parts.append(player.club)
        nat_text = getattr(player, "nationality_display", "") or player.nationality
        if nat_text:
            parts.append(nat_text)
        if parts:
            sub_lbl = QLabel(" · ".join(parts))
            sub_lbl.setStyleSheet("color: #8b949e; font-size: 13px;")
            lay.addWidget(sub_lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #21262d;")
        lay.addWidget(sep)
        return w

    def _build_stats_row(self, player) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 4)

        age = _player_age(player)
        value = _estimated_player_value(player)
        wage = getattr(player, "wage", 0) or 0
        ca = player.current_ability
        pa = player.potential_ability
        rep = player.reputation or 0

        stats = [
            ("Age", str(age) if age else "-"),
            ("CA", str(ca)),
            ("PA", str(pa)),
            ("Rep", str(rep)),
            ("Value", _format_money(value)),
            ("Wage", _format_money(wage)),
        ]
        for label, val in stats:
            cell = QLabel(
                f"<span style='color:#8b949e; font-size:11px;'>{label}</span>"
                f"<br><span style='color:#f0f6fc; font-size:14px; "
                f"font-weight:600;'>{val}</span>"
            )
            cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(cell)

        return w

    def _build_contract_info(self, player) -> QWidget | None:
        parts = []
        if getattr(player, "on_loan", False):
            parent = getattr(player, "parent_club", "")
            if parent:
                parts.append(tr("player.on_loan_from", club=parent))
            else:
                parts.append(tr("player.on_loan"))
        if getattr(player, "transfer_listed", False):
            parts.append(tr("player.transfer_listed"))
        if getattr(player, "loan_listed", False):
            parts.append(tr("player.loan_listed"))

        expiry = getattr(player, "contract_expiry", 0)
        if expiry:
            parts.append(tr("player.contract_expires", date=_format_fm_date(expiry)))

        opt_years = getattr(player, "contract_option_years", 0)
        if opt_years:
            parts.append(tr("player.option_years", years=opt_years))

        clause_rows = self._release_clause_rows(player)
        if clause_rows:
            label, value = clause_rows[0]
            parts.append(f"{label}: {value}")

        league = getattr(player, "league", "")
        if league:
            parts.append(tr("player.league_label", league=league))

        if not parts:
            return None

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 4)
        for line in parts:
            lbl = QLabel(line)
            lbl.setStyleSheet("color: #c9d1d9; font-size: 12px;")
            lay.addWidget(lbl)
        return w

    @staticmethod
    def _release_clause_rows(player) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        defs = (
            ("release_clause", "player.release_clause.min"),
            ("release_clause_foreign", "player.release_clause.foreign"),
            ("release_clause_domestic_higher", "player.release_clause.domestic_higher"),
            ("release_clause_domestic", "player.release_clause.domestic"),
            ("release_clause_continental", "player.release_clause.continental"),
            (
                "release_clause_major_continental",
                "player.release_clause.major_continental",
            ),
        )
        for field, label_key in defs:
            amount = getattr(player, field, 0) or 0
            if amount > 0:
                rows.append((tr(label_key), _format_money(amount)))
        return rows

    def _build_attributes_tab(self, player) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(12)

        columns_lay = QHBoxLayout()
        columns_lay.setSpacing(16)

        main_sections = [
            ("Technical", ATTR_OFFSETS.TECHNICAL_FIELDS),
            ("Mental", ATTR_OFFSETS.MENTAL_FIELDS),
            ("Physical", ATTR_OFFSETS.PHYSICAL_FIELDS),
            ("Goalkeeping", ATTR_OFFSETS.GOALKEEPER_FIELDS),
        ]
        for section_name, fields in main_sections:
            col_w = QWidget()
            col_lay = QVBoxLayout(col_w)
            col_lay.setContentsMargins(0, 0, 0, 0)
            col_lay.setSpacing(1)

            hdr = QLabel(section_name)
            hdr.setStyleSheet("color: #58a6ff; font-size: 11px; font-weight: 700;")
            col_lay.addWidget(hdr)

            for field in fields:
                val = getattr(player, field, 0) or 0
                display = FULL_NAMES.get(field, field)
                row_w = QWidget()
                row_lay = QHBoxLayout(row_w)
                row_lay.setContentsMargins(0, 0, 0, 0)
                row_lay.setSpacing(4)
                name_lbl = QLabel(display)
                name_lbl.setStyleSheet("color: #c9d1d9; font-size: 11px;")
                name_lbl.setMinimumWidth(100)
                spin = self._make_attr_spin(val)
                self._attr_spins[field] = spin
                row_lay.addWidget(name_lbl)
                row_lay.addWidget(spin)
                col_lay.addWidget(row_w)

            col_lay.addStretch()
            columns_lay.addWidget(col_w)

        columns_lay.addStretch()
        outer.addLayout(columns_lay)

        hidden_hdr = QLabel("Hidden")
        hidden_hdr.setStyleSheet("color: #58a6ff; font-size: 11px; font-weight: 700;")
        outer.addWidget(hidden_hdr)

        hidden_row = QHBoxLayout()
        hidden_row.setSpacing(16)
        for field in ATTR_OFFSETS.HIDDEN_FIELDS:
            val = getattr(player, field, 0) or 0
            display = FULL_NAMES.get(field, field)
            lbl = QLabel(display)
            lbl.setStyleSheet("color: #c9d1d9; font-size: 11px;")
            spin = self._make_attr_spin(val)
            self._attr_spins[field] = spin
            hidden_row.addWidget(lbl)
            hidden_row.addWidget(spin)
        hidden_row.addStretch()
        outer.addLayout(hidden_row)

        pers_hdr = QLabel("Personality")
        pers_hdr.setStyleSheet("color: #58a6ff; font-size: 11px; font-weight: 700;")
        outer.addWidget(pers_hdr)

        pers_grid = QGridLayout()
        pers_grid.setSpacing(4)
        pcol = 0
        prow = 0
        for name in PERSONALITY_NAMES:
            val = player.personality.get(name, 0) or 0
            cell = QWidget()
            cell_lay = QHBoxLayout(cell)
            cell_lay.setContentsMargins(0, 0, 0, 0)
            cell_lay.setSpacing(4)
            lbl = QLabel(name)
            lbl.setStyleSheet("color: #c9d1d9; font-size: 11px;")
            lbl.setMinimumWidth(96)
            spin = self._make_attr_spin(val)
            self._pers_spins[name] = spin
            cell_lay.addWidget(lbl)
            cell_lay.addWidget(spin)
            # Absorb the column's spare width here, so the box stays next
            # to its own label instead of drifting toward the next one.
            cell_lay.addStretch()
            pers_grid.addWidget(cell, prow, pcol)
            pcol += 1
            if pcol >= 4:
                pcol = 0
                prow += 1
        outer.addLayout(pers_grid)

        ability_hdr = QLabel(tr("edit.ability"))
        ability_hdr.setStyleSheet("color: #58a6ff; font-size: 11px; font-weight: 700;")
        outer.addWidget(ability_hdr)

        ability_row = QHBoxLayout()
        ability_row.setSpacing(16)
        for label, attr, spin_name in (
            (tr("edit.ca"), "current_ability", "_ca_spin"),
            (tr("edit.pa"), "potential_ability", "_pa_spin"),
        ):
            lbl = QLabel(label)
            lbl.setStyleSheet("color: #c9d1d9; font-size: 11px;")
            spin = _AttrSpinBox(0, 200, getattr(player, attr, 0) or 0, 52)
            spin.setObjectName("abilitySpin")
            setattr(self, spin_name, spin)
            ability_row.addWidget(lbl)
            ability_row.addWidget(spin)
        ability_row.addStretch()
        outer.addLayout(ability_row)

        outer.addStretch()
        scroll.setWidget(w)
        return scroll

    def _make_attr_spin(self, value: int) -> QSpinBox:
        """Editable 1-20 attribute box; 0 shows as '-' and is never written."""
        spin = _AttrSpinBox(0, 20, int(value or 0), 34)
        spin.setSpecialValueText("-")
        self._style_attr_spin(spin, spin.value())
        spin.valueChanged.connect(
            lambda v, s=spin: self._style_attr_spin(s, v)
        )
        return spin

    @staticmethod
    def _style_attr_spin(spin: QSpinBox, value: int):
        """Recolor a spin box by value.

        The full compact style is repeated here because a widget-level
        stylesheet takes precedence over the dialog's SS_ATTR_SPIN rules.
        """
        color = attr_color_hex(value) if value > 0 else "#484f58"
        spin.setStyleSheet(
            "QSpinBox {"
            f"color: {color};"
            "font-weight: 600;"
            "font-size: 11px;"
            "padding: 0px 3px;"
            "min-height: 0px;"
            "border: 1px solid #30363d;"
            "border-radius: 3px;"
            "background-color: #161b22;"
            "}"
        )

    # -- Editing ------------------------------------------------------------

    def _build_edit_bar(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(8)

        self._edit_status = QLabel("")
        self._edit_status.setStyleSheet("color: #8b949e; font-size: 11px;")
        lay.addWidget(self._edit_status, 1)

        import_btn = QPushButton(tr("edit.import"))
        import_btn.clicked.connect(self._import_attributes)
        lay.addWidget(import_btn)

        export_btn = QPushButton(tr("edit.export"))
        export_btn.clicked.connect(self._export_attributes)
        lay.addWidget(export_btn)

        apply_btn = QPushButton(tr("edit.apply"))
        apply_btn.setObjectName("primary")
        apply_btn.clicked.connect(self._apply_edits)
        lay.addWidget(apply_btn)

        return w

    def _on_position_changed(self, pos_name: str, value: int):
        if self._position_pitch is not None:
            self._position_pitch.set_value(pos_name, value)

    def _collect_edits(self) -> tuple[dict[str, int], dict[str, int], dict[str, int], int, int]:
        """Read the current spin box values.

        Values left at 0 (shown as '-') are omitted: they are unset in the
        save, and writing them would turn them into real 1s.
        """
        attributes = {
            field: spin.value()
            for field, spin in self._attr_spins.items()
            if spin.value() > 0
        }
        positions = {
            name: spin.value()
            for name, spin in self._pos_spins.items()
            if spin.value() > 0
        }
        personality = {
            name: spin.value()
            for name, spin in self._pers_spins.items()
            if spin.value() > 0
        }
        ca = self._ca_spin.value() if self._ca_spin else 0
        pa = self._pa_spin.value() if self._pa_spin else 0
        return attributes, positions, personality, ca, pa

    def _set_edit_status(self, text: str, color: str = "#8b949e"):
        self._edit_status.setText(text)
        self._edit_status.setStyleSheet(f"color: {color}; font-size: 11px;")

    def _apply_edits(self):
        attributes, positions, personality, ca, pa = self._collect_edits()

        proc = find_fm_process()
        if proc is None:
            QMessageBox.warning(self, tr("edit.error_title"), tr("msg.no_process"))
            return

        writer = MemoryWriter(proc.pid)
        try:
            writer.open()
        except OSError as e:
            QMessageBox.warning(
                self, tr("edit.error_title"), tr("edit.error_open", error=str(e))
            )
            return

        try:
            profile = CURRENT_PROFILE
            if profile is None:
                raise PlayerWriteError("no scan has been run (scan first)")
            player_writer = PlayerWriter(
                writer,
                profile.struct,
                attribute_byte_offsets=profile.attribute_byte_offsets,
            )
            written, failures = player_writer.apply(
                self._player,
                attributes=attributes,
                positions=positions,
                personality=personality,
                current_ability=ca or None,
                potential_ability=pa or None,
            )
        except PlayerWriteError as e:
            QMessageBox.warning(self, tr("edit.error_title"), str(e))
            return
        except OSError as e:
            QMessageBox.warning(
                self, tr("edit.error_title"), tr("edit.error_write", error=str(e))
            )
            return
        finally:
            writer.close()

        self.player_edited = True
        self._refresh_stats_row()
        if failures:
            self._set_edit_status(
                tr("edit.applied_partial", count=written, failed=len(failures)),
                "#d29922",
            )
        else:
            self._set_edit_status(tr("edit.applied", count=written), "#3fb950")

    def _export_attributes(self):
        attributes, positions, personality, ca, pa = self._collect_edits()
        default_name = (
            "".join(
                c if c.isalnum() or c in "-_" else "_"
                for c in (self._player.display_name or "player")
            )
            + ".json"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, tr("edit.export_title"), default_name, tr("edit.json_filter")
        )
        if not path:
            return
        data = build_export(
            self._player, attributes, positions, personality, ca, pa
        )
        try:
            export_to_file(path, data)
        except OSError as e:
            QMessageBox.warning(
                self, tr("edit.error_title"), tr("edit.error_write", error=str(e))
            )
            return
        self._set_edit_status(tr("edit.exported", path=os.path.basename(path)))

    def _import_attributes(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("edit.import_title"), "", tr("edit.json_filter")
        )
        if not path:
            return
        try:
            attributes, positions, personality, ca, pa = import_from_file(path)
        except (OSError, PlayerWriteError) as e:
            QMessageBox.warning(self, tr("edit.error_title"), str(e))
            return

        loaded = 0
        for field, value in attributes.items():
            spin = self._attr_spins.get(field)
            if spin is not None:
                spin.setValue(value)
                loaded += 1
        for name, value in positions.items():
            spin = self._pos_spins.get(name)
            if spin is not None:
                spin.setValue(value)
                loaded += 1
        for name, value in personality.items():
            spin = self._pers_spins.get(name)
            if spin is not None:
                spin.setValue(value)
                loaded += 1
        if ca is not None and self._ca_spin is not None:
            self._ca_spin.setValue(ca)
            loaded += 1
        if pa is not None and self._pa_spin is not None:
            self._pa_spin.setValue(pa)
            loaded += 1

        self._set_edit_status(tr("edit.imported", count=loaded))

    def _refresh_stats_row(self):
        """Rebuild the CA/PA/value header after a write."""
        layout = self.layout()
        index = layout.indexOf(self._stats_row)
        if index < 0:
            return
        new_row = self._build_stats_row(self._player)
        layout.insertWidget(index, new_row)
        layout.removeWidget(self._stats_row)
        self._stats_row.deleteLater()
        self._stats_row = new_row

    def _build_positions_tab(self, player) -> QWidget:
        tab = QWidget()
        lay = QHBoxLayout(tab)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(16)

        positions = getattr(player, "positions", {}) or {}

        # A copy: the pitch previews pending edits, the player object is
        # only updated once the values are written to the game.
        pitch = _PlayerPositionPitch(dict(positions))
        pitch.setMinimumSize(280, 380)
        self._position_pitch = pitch
        lay.addWidget(pitch, 1)

        list_w = QWidget()
        list_lay = QVBoxLayout(list_w)
        list_lay.setContentsMargins(0, 0, 0, 0)
        list_lay.setSpacing(2)

        hdr = QLabel(tr("player.position_ratings"))
        hdr.setStyleSheet("color: #58a6ff; font-size: 12px; font-weight: 700;")
        list_lay.addWidget(hdr)

        # _POS_COORDS omits SW: the sweeper slot still occupies a byte in
        # the position array, but the role no longer exists in FM24.
        for pos_name in _POS_COORDS:
            val = positions.get(pos_name, 0)
            row_w = QWidget()
            row_lay = QHBoxLayout(row_w)
            row_lay.setContentsMargins(0, 0, 0, 0)
            row_lay.setSpacing(6)
            lbl = QLabel(pos_name)
            lbl.setStyleSheet("color: #c9d1d9; font-size: 12px;")
            lbl.setMinimumWidth(40)
            spin = self._make_attr_spin(val)
            spin.valueChanged.connect(
                lambda v, name=pos_name: self._on_position_changed(name, v)
            )
            self._pos_spins[pos_name] = spin
            row_lay.addWidget(lbl)
            row_lay.addWidget(spin)
            list_lay.addWidget(row_w)

        list_lay.addStretch()
        lay.addWidget(list_w)
        return tab

    def _build_personality_tab(self, player) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        w = QWidget()
        lay = QGridLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)

        col = 0
        row = 0
        for pc in PERSONALITY_COLS:
            val = getattr(player, pc, 0) or 0
            display = pc[5:].replace("_", " ").title()
            color = attr_color_hex(val) if val > 0 else "#484f58"
            lbl = QLabel(
                f"<span style='color:#8b949e;'>{display}:</span> "
                f"<span style='color:{color}; font-weight:600;'>"
                f"{val if val else '-'}</span>"
            )
            lbl.setStyleSheet("font-size: 12px;")
            lay.addWidget(lbl, row, col)
            col += 1
            if col >= 4:
                col = 0
                row += 1

        lay.setRowStretch(row + 1, 1)
        scroll.setWidget(w)
        return scroll

    def _build_contract_tab(self, player) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        club = getattr(player, "club", "") or "-"
        club_lbl = QLabel(
            f"<span style='color:#58a6ff; font-weight:700;'>{club}</span>"
        )
        club_lbl.setStyleSheet("font-size: 14px;")
        lay.addWidget(club_lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #21262d;")
        lay.addWidget(sep)

        wage = getattr(player, "wage", 0) or 0
        expiry = getattr(player, "contract_expiry", 0) or 0
        opt_years = getattr(player, "contract_option_years", 0) or 0
        transfer_opts = getattr(player, "contract_transfer_opts", 0) or 0

        rows = []
        if wage:
            rows.append(("Weekly Wage", _format_money(wage) + " p/w"))
        if expiry:
            rows.append(("Expires", _format_fm_date(expiry)))
        if opt_years:
            rows.append(("Option Years", str(opt_years)))
        if transfer_opts:
            rows.append(("Transfer Options", str(transfer_opts)))
        rows.extend(self._release_clause_rows(player))

        if getattr(player, "on_loan", False):
            parent = getattr(player, "parent_club", "")
            rows.append(("Status", f"On Loan from {parent}" if parent else "On Loan"))
        if getattr(player, "transfer_listed", False):
            rows.append(("Status", "Transfer Listed"))
        if getattr(player, "loan_listed", False):
            rows.append(("Status", "Available for Loan"))

        league = getattr(player, "league", "")
        if league:
            rows.append(("League", league))

        grid = QGridLayout()
        grid.setSpacing(6)
        for i, (label, value) in enumerate(rows):
            l = QLabel(label)
            l.setStyleSheet("color: #8b949e; font-size: 12px;")
            v = QLabel(value)
            v.setStyleSheet("color: #f0f6fc; font-size: 12px; font-weight: 600;")
            grid.addWidget(l, i, 0)
            grid.addWidget(v, i, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)

        if not rows:
            empty = QLabel("No contract information available.")
            empty.setStyleSheet("color: #484f58; font-size: 12px;")
            lay.addWidget(empty)

        lay.addStretch()
        return w

    def _build_traits_tab(self, player) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(4)

        hdr = QLabel("Player Traits")
        hdr.setStyleSheet("color: #58a6ff; font-size: 12px; font-weight: 700;")
        lay.addWidget(hdr)

        traits = getattr(player, "traits", []) or []
        if traits:
            for trait in traits:
                lbl = QLabel(f"\u2022  {trait}")
                lbl.setStyleSheet("color: #c9d1d9; font-size: 12px; padding: 2px 0;")
                lay.addWidget(lbl)
        else:
            empty = QLabel("No player traits.")
            empty.setStyleSheet("color: #484f58; font-size: 12px;")
            lay.addWidget(empty)

        lay.addStretch()
        return w

    @staticmethod
    def _section_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "color: #f0f6fc; font-size: 13px; font-weight: 600; padding: 8px 0 2px 0;"
        )
        return lbl


# ---------------------------------------------------------------------------
# MainWindow
# ---------------------------------------------------------------------------


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(tr("app.title"))
        self.resize(1400, 860)
        self.setStyleSheet(SS_WIDGET)

        self._scan_worker: Optional[ScanWorker] = None
        self._scan_quick_applied = False
        self._active_filters: dict = {}
        self._shortlist_uids: set[int] = set()
        self._hidden_cols: set[str] = set(DEFAULT_HIDDEN_COLS)
        self._all_players: list = []
        self._all_clubs: list = []

        self._filter_continents: list[str] = []
        self._filter_nations: dict[str, list[str]] = {}
        self._filter_leagues: dict[str, list[tuple[str, int]]] = {}
        self._filter_clubs: dict[str, list[str]] = {}
        self._col_pcts: dict[str, float] = {}
        self._resizing_cols = False

        self._build_ui()
        self._restore_column_layout()
        self._apply_column_visibility()

        self._search_table.horizontalHeader().sectionResized.connect(
            self._on_column_resized
        )

        QTimer.singleShot(0, self._apply_col_widths)

    # -- UI construction ---------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Top bar
        top_bar = QHBoxLayout()
        self._scan_btn = QPushButton(tr("button.scan"))
        self._scan_btn.setObjectName("primary")
        self._scan_btn.clicked.connect(self._start_scan)
        top_bar.addWidget(self._scan_btn)

        self._refresh_btn = QPushButton(tr("button.refresh"))
        self._refresh_btn.clicked.connect(self._start_scan)
        self._refresh_btn.setVisible(False)
        top_bar.addWidget(self._refresh_btn)

        self._count_label = QLabel("")
        self._count_label.setStyleSheet(
            "color: #f0f6fc; font-size: 13px; font-weight: 600;"
        )
        top_bar.addWidget(self._count_label)
        top_bar.addStretch()

        from fm_scout.locale import available_languages, get_language, set_language

        self._lang_combo = QComboBox()
        self._lang_combo.setFixedWidth(100)
        for lang in available_languages():
            self._lang_combo.addItem(tr(f"language.{lang}"), lang)
        current = get_language()
        idx = self._lang_combo.findData(current)
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)
        self._lang_combo.currentIndexChanged.connect(self._on_language_changed)
        top_bar.addWidget(self._lang_combo)

        root.addLayout(top_bar)

        # Tab widget
        self._tab_widget = QTabWidget()
        root.addWidget(self._tab_widget)

        self._build_search_tab()
        self._build_shortlist_tab()

        self._tactics_widget = TacticsBuilderWidget()
        self._tab_widget.addTab(self._tactics_widget, tr("tab.tactics"))

        self._club_widget = ClubViewerWidget()
        self._tab_widget.addTab(self._club_widget, tr("tab.clubs"))

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        self._progress_bar.setMaximumWidth(300)
        self._status_bar.addPermanentWidget(self._progress_bar)

        # Hide post-scan widgets
        self._post_scan_widgets = [
            self._refresh_btn,
            self._search_toolbar,
            self._shortlist_toolbar,
        ]
        for w in self._post_scan_widgets:
            w.setVisible(False)

    def _build_search_tab(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(0, 0, 0, 0)

        self._search_toolbar = QWidget()
        tbar = QHBoxLayout(self._search_toolbar)
        tbar.setContentsMargins(0, 4, 0, 4)

        filter_btn = QPushButton(tr("button.filter"))
        filter_btn.clicked.connect(self._open_search_dialog)
        tbar.addWidget(filter_btn)

        clear_btn = QPushButton(tr("button.clear"))
        clear_btn.clicked.connect(self._clear_filters)
        tbar.addWidget(clear_btn)

        add_sl_btn = QPushButton(tr("button.add_shortlist"))
        add_sl_btn.clicked.connect(self._add_to_shortlist)
        tbar.addWidget(add_sl_btn)

        export_btn = QPushButton(tr("button.export_csv"))
        export_btn.clicked.connect(self._export_search_csv)
        tbar.addWidget(export_btn)

        tbar.addStretch()

        self._filter_label = QLabel("")
        self._filter_label.setStyleSheet("color: #58a6ff; font-size: 11px;")
        tbar.addWidget(self._filter_label)

        lay.addWidget(self._search_toolbar)

        self._search_model = PlayerTableModel(self)
        self._search_table = QTableView()
        self._search_table.setModel(self._search_model)
        self._search_table.setStyleSheet(SS_TABLE)
        self._search_table.setSortingEnabled(True)
        self._search_table.setMouseTracking(True)
        self._search_table.viewport().setMouseTracking(True)
        self._search_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._search_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._search_table.verticalHeader().setVisible(False)
        self._search_table.horizontalHeader().setStretchLastSection(False)
        self._search_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self._search_table.doubleClicked.connect(self._on_search_double_click)
        self._search_table.entered.connect(
            lambda idx: self._search_model.set_hover_row(idx.row())
        )
        self._search_table.viewport().installEventFilter(self)

        self._name_delegate = NameBadgeDelegate(self._search_table, self._search_model)
        self._search_table.setItemDelegateForColumn(0, self._name_delegate)

        hdr = self._search_table.horizontalHeader()
        hdr.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        hdr.customContextMenuRequested.connect(self._show_column_menu)

        lay.addWidget(self._search_table)
        self._tab_widget.addTab(tab, tr("tab.search"))

    def _build_shortlist_tab(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(0, 0, 0, 0)

        self._shortlist_toolbar = QWidget()
        tbar = QHBoxLayout(self._shortlist_toolbar)
        tbar.setContentsMargins(0, 4, 0, 4)

        remove_btn = QPushButton(tr("button.remove"))
        remove_btn.clicked.connect(self._remove_from_shortlist)
        tbar.addWidget(remove_btn)

        save_btn = QPushButton(tr("button.save"))
        save_btn.clicked.connect(self._export_shortlist)
        tbar.addWidget(save_btn)

        load_btn = QPushButton(tr("button.load"))
        load_btn.clicked.connect(self._import_shortlist)
        tbar.addWidget(load_btn)

        tbar.addStretch()

        self._shortlist_count = QLabel("")
        self._shortlist_count.setStyleSheet("color: #8b949e; font-size: 11px;")
        tbar.addWidget(self._shortlist_count)

        lay.addWidget(self._shortlist_toolbar)

        self._shortlist_model = PlayerTableModel(self)
        self._shortlist_table = QTableView()
        self._shortlist_table.setModel(self._shortlist_model)
        self._shortlist_table.setStyleSheet(SS_TABLE)
        self._shortlist_table.setSortingEnabled(True)
        self._shortlist_table.setMouseTracking(True)
        self._shortlist_table.viewport().setMouseTracking(True)
        self._shortlist_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._shortlist_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._shortlist_table.verticalHeader().setVisible(False)
        self._shortlist_table.horizontalHeader().setStretchLastSection(False)
        self._shortlist_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self._shortlist_table.doubleClicked.connect(self._on_shortlist_double_click)
        self._shortlist_table.entered.connect(
            lambda idx: self._shortlist_model.set_hover_row(idx.row())
        )
        self._shortlist_table.viewport().installEventFilter(self)

        self._sl_name_delegate = NameBadgeDelegate(
            self._shortlist_table, self._shortlist_model
        )
        self._shortlist_table.setItemDelegateForColumn(0, self._sl_name_delegate)

        sl_hdr = self._shortlist_table.horizontalHeader()
        sl_hdr.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        sl_hdr.customContextMenuRequested.connect(self._show_column_menu)

        lay.addWidget(self._shortlist_table)
        self._tab_widget.addTab(tab, tr("tab.shortlist"))

    # -- Scanning ----------------------------------------------------------

    def _start_scan(self):
        if self._scan_worker and self._scan_worker.isRunning():
            return

        self._scan_btn.setEnabled(False)
        self._refresh_btn.setEnabled(False)
        self._scan_quick_applied = False
        self._progress_bar.setVisible(False)
        self._status_bar.showMessage(tr("msg.scanning"))

        self._scan_worker = ScanWorker()
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.quick_ready.connect(self._on_scan_quick_ready)
        self._scan_worker.finished.connect(self._on_scan_done)
        self._scan_worker.error.connect(self._on_scan_error)
        self._scan_worker.start()

    def _on_scan_progress(self, current: int, total: int, msg: str):
        # Progress updates intentionally hidden for a cleaner scan UX.
        return

    def _apply_scan_players(self, players: list, my_club: str):
        self._all_players = players
        self._search_model.set_all_players(players)
        self._count_label.setText(f"{len(players):,} players")
        self._apply_column_visibility()
        self._rebuild_shortlist_model()
        self._rebuild_filter_options()
        if hasattr(self._tactics_widget, "set_data"):
            try:
                self._tactics_widget.set_data(
                    my_club=my_club,
                    players=players,
                    game_year=GAME_YEAR or 2024,
                )
            except Exception:
                logger.debug("Tactics widget set_data not available yet")

    def _on_scan_quick_ready(self, result: dict):
        players = result.get("players", [])
        my_club = result.get("my_club", "")
        self._apply_scan_players(players, my_club)
        self._scan_quick_applied = True
        self._status_bar.showMessage(tr("msg.scanning"))

    def _on_scan_done(self, result: dict):
        players = result.get("players", [])
        clubs = result.get("clubs", [])
        my_club = result.get("my_club", "")
        game_version = result.get("game_version", "")

        self._all_clubs = clubs
        if not self._scan_quick_applied:
            self._apply_scan_players(players, my_club)

        self._club_widget.set_clubs(clubs, players, GAME_YEAR or 2024)

        self._scan_btn.setEnabled(True)
        self._refresh_btn.setEnabled(True)
        self._progress_bar.setVisible(False)
        for w in self._post_scan_widgets:
            w.setVisible(True)

        if game_version:
            status = tr(
                "msg.scan_complete_version",
                players=f"{len(players):,}",
                clubs=f"{len(clubs):,}",
                version=game_version,
            )
        else:
            status = tr(
                "msg.scan_complete",
                players=f"{len(players):,}",
                clubs=f"{len(clubs):,}",
            )
        self._status_bar.showMessage(status, 5000)

        if self._active_filters:
            self._apply_active_filters()

    def _on_scan_error(self, msg: str):
        self._scan_btn.setEnabled(True)
        self._refresh_btn.setEnabled(True)
        self._progress_bar.setVisible(False)
        self._status_bar.showMessage(tr("msg.error_prefix", msg=msg), 10000)
        QMessageBox.critical(self, tr("msg.scan_error"), msg)

    # -- Column management -------------------------------------------------

    def _show_column_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet(SS_DIALOG)

        default_action = menu.addAction(tr("menu.show_default"))
        default_action.setData("__reset__")
        menu.addSeparator()

        sub_contract = menu.addMenu(tr("menu.contract_status"))
        for col in CONTRACT_EXTRA_COLS:
            act = sub_contract.addAction(MENU_HEADERS.get(col, col))
            act.setCheckable(True)
            act.setChecked(col not in self._hidden_cols)
            act.setData(col)

        sub_tech = menu.addMenu("Technical")
        for field in ATTR_OFFSETS.TECHNICAL_FIELDS:
            act = sub_tech.addAction(MENU_HEADERS.get(field, field))
            act.setCheckable(True)
            act.setChecked(field not in self._hidden_cols)
            act.setData(field)

        sub_mental = menu.addMenu("Mental")
        for field in ATTR_OFFSETS.MENTAL_FIELDS:
            act = sub_mental.addAction(MENU_HEADERS.get(field, field))
            act.setCheckable(True)
            act.setChecked(field not in self._hidden_cols)
            act.setData(field)

        sub_phys = menu.addMenu("Physical")
        for field in ATTR_OFFSETS.PHYSICAL_FIELDS:
            act = sub_phys.addAction(MENU_HEADERS.get(field, field))
            act.setCheckable(True)
            act.setChecked(field not in self._hidden_cols)
            act.setData(field)

        sub_gk = menu.addMenu("Goalkeeping")
        for field in ATTR_OFFSETS.GOALKEEPER_FIELDS:
            act = sub_gk.addAction(MENU_HEADERS.get(field, field))
            act.setCheckable(True)
            act.setChecked(field not in self._hidden_cols)
            act.setData(field)

        sub_hidden = menu.addMenu("Hidden")
        for field in ATTR_OFFSETS.HIDDEN_FIELDS:
            act = sub_hidden.addAction(MENU_HEADERS.get(field, field))
            act.setCheckable(True)
            act.setChecked(field not in self._hidden_cols)
            act.setData(field)

        sub_pers = menu.addMenu("Personality")
        for pc in PERSONALITY_COLS:
            act = sub_pers.addAction(MENU_HEADERS.get(pc, pc))
            act.setCheckable(True)
            act.setChecked(pc not in self._hidden_cols)
            act.setData(pc)

        chosen = menu.exec(self._search_table.horizontalHeader().mapToGlobal(pos))
        if chosen is None:
            return

        col_data = chosen.data()
        if col_data == "__reset__":
            self._hidden_cols = set(DEFAULT_HIDDEN_COLS)
        elif col_data:
            if col_data in self._hidden_cols:
                self._hidden_cols.discard(col_data)
            else:
                self._hidden_cols.add(col_data)

        self._apply_column_visibility()
        self._save_column_layout()

    _DEFAULT_COL_PCTS: dict[str, float] = {
        "name": 15.0,
        "club": 15.0,
        "nationality": 10.0,
        "age": 4.0,
        "best_pos": 8.0,
        "est_value": 7.0,
        "wage": 6.0,
        "ca": 4.0,
        "pa": 4.0,
        "reputation": 5.0,
    }
    _DEFAULT_ATTR_PCT = 3.5

    def _get_col_pcts(self) -> dict[str, float]:
        """Return current percentage for each visible column."""
        visible = [c for c in TABLE_COLS if c not in self._hidden_cols]
        if not visible:
            return {}
        pcts: dict[str, float] = {}
        for c in visible:
            if c in self._col_pcts:
                pcts[c] = self._col_pcts[c]
            elif c in self._DEFAULT_COL_PCTS:
                pcts[c] = self._DEFAULT_COL_PCTS[c]
            else:
                pcts[c] = self._DEFAULT_ATTR_PCT
        total = sum(pcts.values())
        if total > 0:
            for c in pcts:
                pcts[c] = pcts[c] / total * 100.0
        return pcts

    def _apply_col_widths(self):
        """Distribute column widths proportionally across the table width."""
        if self._resizing_cols:
            return
        self._resizing_cols = True
        pcts = self._get_col_pcts()
        for table in (self._search_table, self._shortlist_table):
            tw = table.viewport().width()
            if tw <= 1:
                tw = table.width() - 2
            for col_name, pct in pcts.items():
                idx = COL_INDEX.get(col_name, -1)
                if idx >= 0:
                    table.setColumnWidth(idx, max(28, int(tw * pct / 100.0)))
        self._resizing_cols = False

    def _apply_column_visibility(self):
        for i, col_name in enumerate(TABLE_COLS):
            hidden = col_name in self._hidden_cols
            self._search_table.setColumnHidden(i, hidden)
            self._shortlist_table.setColumnHidden(i, hidden)
        self._apply_col_widths()

    def _on_column_resized(self, idx: int, old_w: int, new_w: int):
        """When user drags a column, recalculate percentages from actual widths."""
        if self._resizing_cols:
            return
        table = self._search_table
        tw = table.viewport().width()
        if tw <= 1:
            return
        visible = [c for c in TABLE_COLS if c not in self._hidden_cols]
        for c in visible:
            ci = COL_INDEX.get(c, -1)
            if ci >= 0:
                self._col_pcts[c] = table.columnWidth(ci) / tw * 100.0

    def _save_column_layout(self):
        settings = QSettings("FMScout", "FMScout")
        settings.setValue("table_layout_version", TABLE_LAYOUT_VERSION)
        settings.setValue("hidden_columns", list(self._hidden_cols))
        settings.setValue("column_pcts", dict(self._col_pcts))

    def _restore_column_layout(self):
        settings = QSettings("FMScout", "FMScout")
        version = settings.value("table_layout_version", 0, type=int)
        if version != TABLE_LAYOUT_VERSION:
            return
        hidden = settings.value("hidden_columns", None)
        if hidden is not None:
            self._hidden_cols = set(hidden)
        saved_pcts = settings.value("column_pcts", None)
        if saved_pcts and isinstance(saved_pcts, dict):
            self._col_pcts = {k: float(v) for k, v in saved_pcts.items()}

    # -- Filter system -----------------------------------------------------

    _SENIOR_LEAGUE_TYPES = {0, 1, 14}

    def _rebuild_filter_options(self):
        nat_continents: set[str] = set()
        nat_by_continent: dict[str, set[str]] = {}
        nation_to_continent: dict[str, str] = {}

        club_continents: set[str] = set()
        club_nations_by_continent: dict[str, set[str]] = {}
        leagues_by_nation: dict[str, dict[str, int]] = {}
        clubs_by_league: dict[str, set[str]] = {}

        for p in self._all_players:
            nationality = getattr(p, "nationality", "") or ""
            league_continent = getattr(p, "league_continent", "") or ""
            league_nation = getattr(p, "league_nation", "") or ""
            league = getattr(p, "league", "") or ""
            club = getattr(p, "club", "") or ""
            rep = getattr(p, "reputation", 0) or 0

            league_type = getattr(p, "league_type", -1)
            if league_type not in self._SENIOR_LEAGUE_TYPES:
                continue

            if league_nation and league_continent:
                nation_to_continent.setdefault(league_nation, league_continent)

            player_nationalities = list(getattr(p, "nationalities", []) or [])
            if not player_nationalities and nationality:
                player_nationalities = [nationality]
            player_nat_conts = list(getattr(p, "nationality_continents", []) or [])

            for idx, nat_name in enumerate(player_nationalities):
                if not nat_name:
                    continue
                ncont = player_nat_conts[idx] if idx < len(player_nat_conts) else ""
                if not ncont:
                    ncont = nation_to_continent.get(nat_name, "")
                if not ncont:
                    continue
                nat_continents.add(ncont)
                nat_by_continent.setdefault(ncont, set()).add(nat_name)

            if league_continent:
                club_continents.add(league_continent)
                if league_nation:
                    club_nations_by_continent.setdefault(league_continent, set()).add(
                        league_nation
                    )

            if league_nation and league:
                leagues_by_nation.setdefault(league_nation, {})
                if league not in leagues_by_nation[league_nation]:
                    leagues_by_nation[league_nation][league] = 0
                if rep > leagues_by_nation[league_nation][league]:
                    leagues_by_nation[league_nation][league] = rep

            if league and club:
                clubs_by_league.setdefault(league, set()).add(club)

        self._filter_nat_continents = sorted(nat_continents)
        self._filter_nat_nations = {k: sorted(v) for k, v in nat_by_continent.items()}
        self._nation_to_continent = dict(nation_to_continent)

        self._filter_club_continents = sorted(club_continents)
        self._filter_club_nations = {
            k: sorted(v) for k, v in club_nations_by_continent.items()
        }

        self._filter_leagues = {}
        for nation, leagues in leagues_by_nation.items():
            league_list = [(name, rep) for name, rep in leagues.items()]
            league_list.sort(key=lambda x: x[1], reverse=True)
            self._filter_leagues[nation] = league_list

        self._filter_clubs = {k: sorted(v) for k, v in clubs_by_league.items()}

    def _open_search_dialog(self):
        filter_data = {
            "nat_continents": self._filter_nat_continents,
            "nat_nations": self._filter_nat_nations,
            "club_continents": self._filter_club_continents,
            "club_nations": self._filter_club_nations,
            "leagues": self._filter_leagues,
            "clubs": self._filter_clubs,
        }
        dlg = SearchDialog(filter_data, self._active_filters, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._active_filters = dlg.get_filters()
            self._apply_active_filters()

    def _apply_active_filters(self):
        f = self._active_filters
        if not f:
            self._search_model.filter()
            self._filter_label.setText("")
            return

        def _fold(s: str) -> str:
            if not s:
                return ""
            # FM-style transliteration: allow "ss" to match German sharp-s.
            s = s.replace("ß", "ss").replace("ẞ", "ss")
            return (
                unicodedata.normalize("NFKD", s)
                .encode("ascii", "ignore")
                .decode("ascii")
                .lower()
            )

        name_query = _fold(f.get("name", ""))
        nation_to_continent = getattr(self, "_nation_to_continent", {})

        def predicate(player) -> bool:
            if name_query:
                pname = _fold(getattr(player, "display_name", "") or "")
                if name_query not in pname:
                    first = _fold(getattr(player, "first_name", "") or "")
                    last = _fold(getattr(player, "last_name", "") or "")
                    if name_query not in first and name_query not in last:
                        return False

            if f.get("nat_continent"):
                selected_continent = f["nat_continent"]
                p_nationalities = list(getattr(player, "nationalities", []) or [])
                if not p_nationalities:
                    primary_nat = getattr(player, "nationality", "") or ""
                    if primary_nat:
                        p_nationalities = [primary_nat]
                p_nat_continents = list(
                    getattr(player, "nationality_continents", []) or []
                )
                if not p_nat_continents and p_nationalities:
                    p_nat_continents = [
                        nation_to_continent.get(n, "") for n in p_nationalities
                    ]
                if selected_continent not in p_nat_continents:
                    return False

            if f.get("nationality"):
                selected_nationality = f["nationality"]
                p_nationalities = list(getattr(player, "nationalities", []) or [])
                if not p_nationalities:
                    primary_nat = getattr(player, "nationality", "") or ""
                    if primary_nat:
                        p_nationalities = [primary_nat]
                if selected_nationality not in p_nationalities:
                    return False

            if f.get("club_continent"):
                pc = getattr(player, "league_continent", "") or ""
                if pc != f["club_continent"]:
                    return False

            if f.get("club_nation"):
                ln = getattr(player, "league_nation", "") or ""
                if ln != f["club_nation"]:
                    return False

            if f.get("league"):
                if (getattr(player, "league", "") or "") != f["league"]:
                    return False

            if f.get("club"):
                if (getattr(player, "club", "") or "") != f["club"]:
                    return False

            age = _player_age(player)
            if f.get("age_min") and age < f["age_min"]:
                return False
            if f.get("age_max") and age > f["age_max"]:
                return False

            ca = player.current_ability
            if f.get("ca_min") and ca < f["ca_min"]:
                return False
            if f.get("ca_max") and ca > f["ca_max"]:
                return False

            pa = player.potential_ability
            if f.get("pa_min") and pa < f["pa_min"]:
                return False
            if f.get("pa_max") and pa > f["pa_max"]:
                return False

            rep = player.reputation or 0
            if f.get("rep_min") and rep < f["rep_min"]:
                return False
            if f.get("rep_max") and rep > f["rep_max"]:
                return False

            wage_eur = gbp_to_eur(getattr(player, "wage", 0) or 0)
            if f.get("wage_min") and wage_eur < f["wage_min"]:
                return False
            if f.get("wage_max") and wage_eur > f["wage_max"]:
                return False

            est_value_eur = gbp_to_eur(_estimated_player_value(player))
            if f.get("est_value_min") and est_value_eur < f["est_value_min"]:
                return False
            if f.get("est_value_max") and est_value_eur > f["est_value_max"]:
                return False

            clause_filter_active = bool(
                f.get("release_clause_min") or f.get("release_clause_max")
            )
            clause_eur = gbp_to_eur(_min_release_clause(player))
            if clause_filter_active and clause_eur <= 0:
                # If user is filtering by release clause, exclude players that
                # have no clause at all (previously leaked through max-only).
                return False
            if f.get("release_clause_min") and clause_eur < f["release_clause_min"]:
                return False
            if f.get("release_clause_max") and clause_eur > f["release_clause_max"]:
                return False

            contract_status = f.get("contract_status")
            if contract_status and not _matches_contract_status(
                player, contract_status
            ):
                return False

            pos_filters = f.get("positions", {})
            if pos_filters:
                positions = getattr(player, "positions", {}) or {}
                for pos, min_val in pos_filters.items():
                    if min_val > 0:
                        player_val = positions.get(pos, 0)
                        if player_val < min_val:
                            return False

            attr_filters = f.get("attrs", {})
            for attr, (amin, amax) in attr_filters.items():
                val = getattr(player, attr, 0) or 0
                if amin > 0 and val < amin:
                    return False
                if amax > 0 and val > amax:
                    return False

            required_traits = f.get("traits", [])
            if required_traits:
                player_traits = set(getattr(player, "traits", []) or [])
                for trait in required_traits:
                    if trait not in player_traits:
                        return False

            return True

        self._search_model.filter(predicate)

        parts = []
        if f.get("nationality"):
            parts.append(f["nationality"])
        if f.get("club_continent"):
            parts.append(f["club_continent"])
        if f.get("club_nation"):
            parts.append(f["club_nation"])
        if f.get("league"):
            parts.append(f["league"])
        if f.get("club"):
            parts.append(f["club"])
        if f.get("contract_status"):
            parts.append(tr(f"filter.contract_status_option.{f['contract_status']}"))
        n = len(self._search_model.get_view_players())
        desc = " › ".join(parts) if parts else tr("msg.custom_filter")
        self._filter_label.setText(f"{desc} ({n:,} results)")

    def _clear_filters(self):
        self._active_filters = {}
        self._search_model.filter()
        self._filter_label.setText("")

    # -- Shortlist ---------------------------------------------------------

    def _add_to_shortlist(self):
        indexes = self._search_table.selectionModel().selectedRows()
        if not indexes:
            return
        added = 0
        for idx in indexes:
            player = self._search_model.get_player(idx.row())
            if player and hasattr(player, "uid") and player.uid:
                if player.uid not in self._shortlist_uids:
                    self._shortlist_uids.add(player.uid)
                    added += 1
        if added:
            self._rebuild_shortlist_model()
            self._status_bar.showMessage(tr("msg.added_shortlist", count=added), 3000)

    def _remove_from_shortlist(self):
        indexes = self._shortlist_table.selectionModel().selectedRows()
        if not indexes:
            return
        removed = 0
        for idx in indexes:
            player = self._shortlist_model.get_player(idx.row())
            if player and hasattr(player, "uid") and player.uid:
                self._shortlist_uids.discard(player.uid)
                removed += 1
        if removed:
            self._rebuild_shortlist_model()
            self._status_bar.showMessage(
                tr("msg.removed_shortlist", count=removed), 3000
            )

    def _rebuild_shortlist_model(self):
        if not self._shortlist_uids:
            self._shortlist_model.set_all_players([])
            self._shortlist_count.setText("")
            return

        shortlisted = [
            p
            for p in self._all_players
            if hasattr(p, "uid") and p.uid in self._shortlist_uids
        ]
        self._shortlist_model.set_all_players(shortlisted)
        self._apply_column_visibility()
        self._shortlist_count.setText(f"{len(shortlisted)} players")

    def _export_shortlist(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr("file_dialog.save_shortlist"), "", tr("file_dialog.csv_filter")
        )
        if not path:
            return

        players = self._shortlist_model.get_all_players()
        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(
                    [
                        "UID",
                        "Name",
                        "Club",
                        "Position",
                        "CA",
                        "PA",
                        "Age",
                        "Nationality",
                        "Value",
                    ]
                )
                for p in players:
                    writer.writerow(
                        [
                            p.uid,
                            getattr(p, "display_name", ""),
                            getattr(p, "club", ""),
                            getattr(p, "best_position", ""),
                            p.current_ability,
                            p.potential_ability,
                            _player_age(p),
                            getattr(p, "nationality", ""),
                            gbp_to_eur(_estimated_player_value(p)),
                        ]
                    )
            self._status_bar.showMessage(
                tr("msg.saved_shortlist", count=len(players), path=path), 5000
            )
        except OSError as e:
            QMessageBox.warning(self, tr("msg.export_error"), str(e))

    def _import_shortlist(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("file_dialog.load_shortlist"), "", tr("file_dialog.csv_filter")
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as fh:
                reader = csv.reader(fh)
                header = next(reader, None)
                imported_uids: set[int] = set()
                for row in reader:
                    if row:
                        try:
                            imported_uids.add(int(row[0]))
                        except (ValueError, IndexError):
                            pass

            before = len(self._shortlist_uids)
            self._shortlist_uids |= imported_uids
            added = len(self._shortlist_uids) - before
            self._rebuild_shortlist_model()
            self._status_bar.showMessage(tr("msg.loaded_shortlist", count=added), 5000)
        except OSError as e:
            QMessageBox.warning(self, tr("msg.import_error"), str(e))

    def _export_search_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr("file_dialog.export_players"), "", tr("file_dialog.csv_filter")
        )
        if not path:
            return

        players = self._search_model.get_view_players()
        visible_cols = [c for c in TABLE_COLS if c not in self._hidden_cols]
        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow([MENU_HEADERS.get(c, c) for c in visible_cols])
                for p in players:
                    row_data = []
                    for col in visible_cols:
                        val = _col_value(p, col)
                        if col == "est_value":
                            row_data.append(gbp_to_eur(_estimated_player_value(p)))
                        elif col == "wage":
                            row_data.append(gbp_to_eur(getattr(p, "wage", 0) or 0))
                        elif col == "contract_expiry":
                            row_data.append(_format_fm_date(val) if val else "")
                        elif col in ("transfer_listed", "loan_listed", "on_loan"):
                            row_data.append("Yes" if val else "")
                        else:
                            row_data.append(val if val is not None else "")
                    writer.writerow(row_data)

            self._status_bar.showMessage(
                tr("msg.exported_players", count=len(players), path=path), 5000
            )
        except OSError as e:
            QMessageBox.warning(self, tr("msg.export_error"), str(e))

    # -- Double click detail -----------------------------------------------

    def _on_search_double_click(self, index: QModelIndex):
        player = self._search_model.get_player(index.row())
        if player:
            dlg = PlayerDetailDialog(player, parent=self)
            dlg.exec()
            if dlg.player_edited:
                self._search_model.refresh_row(index.row())
                self._shortlist_model.refresh_all()

    def _on_shortlist_double_click(self, index: QModelIndex):
        player = self._shortlist_model.get_player(index.row())
        if player:
            dlg = PlayerDetailDialog(player, parent=self)
            dlg.exec()
            if dlg.player_edited:
                self._shortlist_model.refresh_row(index.row())
                self._search_model.refresh_all()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Leave:
            if obj is self._search_table.viewport():
                self._search_model.clear_hover_row()
            elif obj is self._shortlist_table.viewport():
                self._shortlist_model.clear_hover_row()
        return super().eventFilter(obj, event)

    # -- Close event -------------------------------------------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_col_widths()

    def _on_language_changed(self, index: int):
        lang = self._lang_combo.currentData()
        if lang:
            from fm_scout.locale import set_language

            set_language(lang)
            settings = QSettings("FMScout", "FMScout")
            settings.setValue("language", lang)
            QMessageBox.information(
                self,
                tr("app.title"),
                "Language changed. Please restart the application for full effect.",
            )

    def closeEvent(self, event):
        self._save_column_layout()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    from fm_scout.locale import set_language

    settings = QSettings("FMScout", "FMScout")
    saved_lang = settings.value("language", "en", type=str)
    set_language(saved_lang)
    saved_fx = settings.value("gbp_to_eur_rate", DEFAULT_GBP_TO_EUR_RATE, type=float)
    set_gbp_to_eur_rate(saved_fx)
    if not settings.contains("gbp_to_eur_rate"):
        settings.setValue("gbp_to_eur_rate", saved_fx)

    from PyQt6.QtGui import QPalette

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(13, 17, 23))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(201, 209, 217))
    palette.setColor(QPalette.ColorRole.Base, QColor(13, 17, 23))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(22, 27, 34))
    palette.setColor(QPalette.ColorRole.Text, QColor(201, 209, 217))
    palette.setColor(QPalette.ColorRole.Button, QColor(22, 27, 34))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(201, 209, 217))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(240, 246, 252))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(31, 111, 235))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(240, 246, 252))
    palette.setColor(QPalette.ColorRole.Link, QColor(88, 166, 255))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(22, 27, 34))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(201, 209, 217))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(110, 118, 129))
    palette.setColor(QPalette.ColorRole.Mid, QColor(48, 54, 61))
    palette.setColor(QPalette.ColorRole.Dark, QColor(13, 17, 23))
    palette.setColor(QPalette.ColorRole.Shadow, QColor(1, 4, 9))
    app.setPalette(palette)

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
