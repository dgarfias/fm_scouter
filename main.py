#!/usr/bin/env python3
import logging
import math
import os
import sys
import csv
import signal
from datetime import date, timedelta
from typing import Optional

from PyQt6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, QRectF,
    QThread, QSettings, QTimer, pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QFontMetrics
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QTableView, QHeaderView, QLineEdit, QComboBox,
    QPushButton, QLabel, QStatusBar, QMessageBox, QAbstractItemView,
    QDialog, QScrollArea, QFrame, QSpinBox, QGroupBox, QFormLayout, QMenu,
    QTabWidget, QDialogButtonBox, QCheckBox, QFileDialog, QProgressBar,
    QStyledItemDelegate, QStyleOptionViewItem, QStyle,
)

from fm_scout.process import find_fm_process, get_memory_regions
from fm_scout.memory import MemoryReader
from fm_scout.scanner import GameScanner
from fm_scout.offsets import ATTR_OFFSETS, STRUCT_OFFSETS, POSITION_NAMES, PERSONALITY_NAMES
from fm_scout.player import PlayerReader, Player, PlayerAttributes
from fm_scout.tactics_ui import TacticsBuilderWidget
from fm_scout.club_ui import ClubViewerWidget
from fm_scout.club import ClubReader, enrich_clubs_with_players

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger('fm_scout')


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

SHORT_NAMES = {
    'crossing':         'Cro',
    'dribbling':        'Dri',
    'finishing':        'Fin',
    'heading':          'Hea',
    'long_shots':       'Lon',
    'marking':          'Mar',
    'passing':          'Pas',
    'penalty_taking':   'Pen',
    'tackling':         'Tck',
    'first_touch':      'Fir',
    'technique':        'Tec',
    'corners':          'Cor',
    'long_throws':      'LTh',
    'free_kick_taking': 'Fre',
    'off_the_ball':     'OtB',
    'vision':           'Vis',
    'anticipation':     'Ant',
    'decisions':        'Dec',
    'positioning':      'Pos',
    'flair':            'Fla',
    'teamwork':         'Tea',
    'work_rate':        'Wor',
    'leadership':       'Ldr',
    'bravery':          'Bra',
    'aggression':       'Agg',
    'determination':    'Det',
    'composure':        'Cmp',
    'concentration':    'Cnt',
    'acceleration':     'Acc',
    'strength':         'Str',
    'stamina':          'Sta',
    'pace':             'Pac',
    'jumping_reach':    'Jum',
    'balance':          'Bal',
    'agility':          'Agi',
    'natural_fitness':  'Nat',
    'handling':         'Han',
    'aerial_reach':     'Aer',
    'command_of_area':  'Cmd',
    'communication':    'Com',
    'kicking':          'Kic',
    'throwing':         'Thr',
    'one_on_ones':      '1v1',
    'reflexes':         'Ref',
    'eccentricity':     'Ecc',
    'rushing_out':      'Rus',
    'punching':         'Pun',
    'left_foot':        'LFt',
    'right_foot':       'RFt',
    'dirtiness':        'Dir',
    'consistency':      'Con',
    'important_matches': 'Imp',
    'injury_proneness': 'Inj',
    'versatility':      'Ver',
}

FULL_NAMES = {
    'crossing':         'Crossing',
    'dribbling':        'Dribbling',
    'finishing':        'Finishing',
    'heading':          'Heading',
    'long_shots':       'Long Shots',
    'marking':          'Marking',
    'passing':          'Passing',
    'penalty_taking':   'Penalty Taking',
    'tackling':         'Tackling',
    'first_touch':      'First Touch',
    'technique':        'Technique',
    'corners':          'Corners',
    'long_throws':      'Long Throws',
    'free_kick_taking': 'Free Kick Taking',
    'off_the_ball':     'Off The Ball',
    'vision':           'Vision',
    'anticipation':     'Anticipation',
    'decisions':        'Decisions',
    'positioning':      'Positioning',
    'flair':            'Flair',
    'teamwork':         'Teamwork',
    'work_rate':        'Work Rate',
    'leadership':       'Leadership',
    'bravery':          'Bravery',
    'aggression':       'Aggression',
    'determination':    'Determination',
    'composure':        'Composure',
    'concentration':    'Concentration',
    'acceleration':     'Acceleration',
    'strength':         'Strength',
    'stamina':          'Stamina',
    'pace':             'Pace',
    'jumping_reach':    'Jumping Reach',
    'balance':          'Balance',
    'agility':          'Agility',
    'natural_fitness':  'Natural Fitness',
    'handling':         'Handling',
    'aerial_reach':     'Aerial Reach',
    'command_of_area':  'Command of Area',
    'communication':    'Communication',
    'kicking':          'Kicking',
    'throwing':         'Throwing',
    'one_on_ones':      'One on Ones',
    'reflexes':         'Reflexes',
    'eccentricity':     'Eccentricity',
    'rushing_out':      'Rushing Out',
    'punching':         'Punching',
    'left_foot':        'Left Foot',
    'right_foot':       'Right Foot',
    'dirtiness':        'Dirtiness',
    'consistency':      'Consistency',
    'important_matches': 'Important Matches',
    'injury_proneness': 'Injury Proneness',
    'versatility':      'Versatility',
}

CONTRACT_EXTRA_COLS = [
    'transfer_listed', 'loan_listed', 'on_loan', 'parent_club', 'league',
    'contract_expiry', 'contract_transfer_opts', 'contract_option_years',
    'listed_reason',
]

DEFAULT_VISIBLE_COLS = [
    'name', 'club', 'nationality', 'age', 'best_pos',
    'est_value', 'wage', 'ca', 'pa', 'reputation',
]

TABLE_COLS = (
    DEFAULT_VISIBLE_COLS
    + CONTRACT_EXTRA_COLS
    + list(ATTR_COLUMNS)
    + PERSONALITY_COLS
)

COL_INDEX = {name: idx for idx, name in enumerate(TABLE_COLS)}

DEFAULT_HIDDEN_COLS = set(TABLE_COLS) - set(DEFAULT_VISIBLE_COLS)

TABLE_LAYOUT_VERSION = 5

# Short header labels for table columns
COL_HEADERS = {
    'name': 'Name',     'club': 'Club',      'nationality': 'Nat',
    'age': 'Age',       'best_pos': 'Pos',    'est_value': 'Value',
    'wage': 'Wage',     'ca': 'CA',           'pa': 'PA',
    'reputation': 'Rep',
    'transfer_listed': 'TL',       'loan_listed': 'LL',
    'on_loan': 'Loan',             'parent_club': 'Parent',
    'league': 'League',            'contract_expiry': 'Exp',
    'contract_transfer_opts': 'TrOpt',
    'contract_option_years': 'OptY',
    'listed_reason': 'Reason',
}
for _a in ATTR_COLUMNS:
    COL_HEADERS[_a] = SHORT_NAMES[_a]
for _pc in PERSONALITY_COLS:
    COL_HEADERS[_pc] = _pc[5:].title()[:4]

# Full header labels for menus
MENU_HEADERS = {
    'name': 'Name',                 'club': 'Club',
    'nationality': 'Nationality',   'age': 'Age',
    'best_pos': 'Best Position',    'est_value': 'Estimated Value',
    'wage': 'Wage',                 'ca': 'Current Ability',
    'pa': 'Potential Ability',      'reputation': 'Reputation',
    'transfer_listed': 'Transfer Listed',
    'loan_listed': 'Loan Listed',   'on_loan': 'On Loan',
    'parent_club': 'Parent Club',   'league': 'League',
    'contract_expiry': 'Contract Expiry',
    'contract_transfer_opts': 'Transfer Options',
    'contract_option_years': 'Option Years',
    'listed_reason': 'Listed Reason',
}
for _a in ATTR_COLUMNS:
    MENU_HEADERS[_a] = FULL_NAMES[_a]
for _pc in PERSONALITY_COLS:
    MENU_HEADERS[_pc] = _pc[5:].replace('_', ' ').title()


# ---------------------------------------------------------------------------
# Game state (set during scan)
# ---------------------------------------------------------------------------

GAME_YEAR = 0
GAME_DAY = 0

# Estimated value model coefficients
EST_BASE_SCALE = 5_000_000
EST_CA_EXP = 3.0
EST_PA_WEIGHT = 0.8
EST_AGE_PEAK = 27
EST_AGE_DECAY = 0.06
EST_POS_MULTIPLIERS = {
    'ST': 1.25, 'AMC': 1.15, 'AML': 1.10, 'AMR': 1.10,
    'MC': 1.00, 'ML': 0.95, 'MR': 0.95, 'DM': 0.95,
    'DC': 0.90, 'DL': 0.85, 'DR': 0.85,
    'WBL': 0.85, 'WBR': 0.85, 'GK': 0.70,
}
GBP_TO_EUR = 1.17


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
    selection-background-color: #1f6feb;
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


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def attr_color(val: int) -> QColor:
    if val >= 19:
        return QColor('#3fb950')
    if val >= 17:
        return QColor('#58a6ff')
    if val >= 14:
        return QColor('#8b949e')
    if val >= 10:
        return QColor('#d29922')
    if val >= 6:
        return QColor('#db6d28')
    return QColor('#f85149')


def attr_color_hex(val: int) -> str:
    if val >= 19:
        return '#3fb950'
    if val >= 17:
        return '#58a6ff'
    if val >= 14:
        return '#8b949e'
    if val >= 10:
        return '#d29922'
    if val >= 6:
        return '#db6d28'
    return '#f85149'


def _ca_pa_color(val: int) -> QColor:
    """Color for current/potential ability (0-200 scale)."""
    if val >= 170:
        return QColor('#3fb950')
    if val >= 140:
        return QColor('#58a6ff')
    if val >= 110:
        return QColor('#8b949e')
    if val >= 80:
        return QColor('#d29922')
    if val >= 50:
        return QColor('#db6d28')
    return QColor('#f85149')


def _player_age(player) -> int:
    if not player.birth_year or player.birth_year < 1900:
        return 0
    age = GAME_YEAR - player.birth_year
    if GAME_DAY and getattr(player, 'birth_day', 0):
        if GAME_DAY < player.birth_day:
            age -= 1
    return max(0, age)


def _format_money(val) -> str:
    if val is None or val <= 0:
        return ''
    val = int(val)
    if val >= 1_000_000:
        return f'€{val / 1_000_000:.1f}M'
    if val >= 1_000:
        return f'€{val / 1_000:.0f}k'
    return f'€{val:,}'


def _format_fm_date(packed: int) -> str:
    if not packed:
        return ''
    year = (packed >> 16) & 0xFFFF
    day = packed & 0xFFFF
    if year == 0 or day == 0:
        return ''
    try:
        dt = date(year, 1, 1) + timedelta(days=day - 1)
        return dt.strftime('%d %b %Y')
    except (ValueError, OverflowError):
        return ''


def _estimated_player_value(player) -> int:
    ca = player.current_ability
    if ca <= 0:
        return 0

    pa = player.potential_ability or ca
    age = _player_age(player)
    rep = player.reputation or 0
    pos = getattr(player, 'best_position', '') or ''

    base = EST_BASE_SCALE * (ca / 100) ** EST_CA_EXP

    if pa > ca and age < EST_AGE_PEAK:
        potential_ratio = pa / max(ca, 1)
        youth_factor = max(0, EST_AGE_PEAK - age) / 12
        base *= 1 + EST_PA_WEIGHT * (potential_ratio - 1) * youth_factor

    if age > EST_AGE_PEAK:
        decay = EST_AGE_DECAY * (age - EST_AGE_PEAK) ** 1.3
        base *= max(0.05, 1 - decay)
    elif age < 22:
        base *= 0.7 + 0.3 * max(0, age - 15) / 7

    if rep > 0:
        rep_factor = (rep / 10000) ** 0.6
        base *= 0.6 + 0.4 * rep_factor
    else:
        base *= 0.5

    pos_mult = EST_POS_MULTIPLIERS.get(pos, 1.0)
    base *= pos_mult

    return max(0, int(base * GBP_TO_EUR))


_COL_PLAYER_MAP = {
    'name': 'display_name',
    'best_pos': 'best_position',
    'ca': 'current_ability',
    'pa': 'potential_ability',
}


def _col_value(player, col_name: str):
    if col_name == 'age':
        return _player_age(player)
    if col_name == 'est_value':
        return _estimated_player_value(player)
    attr_name = _COL_PLAYER_MAP.get(col_name, col_name)
    return getattr(player, attr_name, None)


# ---------------------------------------------------------------------------
# Badge system
# ---------------------------------------------------------------------------

_BADGE_DEFS = [
    ("on_loan",         "LND", QColor(210, 153, 34)),    # yellow
    ("transfer_listed", "TRF", QColor(248, 81, 73)),     # red
    ("loan_listed",     "LDS", QColor(63, 185, 80)),     # green
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

    def paint(self, painter: QPainter, option: QStyleOptionViewItem,
              index: QModelIndex):
        painter.save()
        painter.setClipRect(option.rect)

        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)

        if is_selected:
            painter.fillRect(option.rect, option.palette.highlight())
        else:
            bg = option.palette.base().color()
            painter.fillRect(option.rect, bg)

        model = self._model_ref
        player = None
        if model is not None:
            player = model.get_player(index.row())

        name = index.data(Qt.ItemDataRole.DisplayRole) or ''

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

    def set_all_players(self, players: list):
        self.beginResetModel()
        self._all_players = list(players)
        self._view = list(players)
        self._sort_col = -1
        self.endResetModel()

    def filter(self, predicate=None):
        self.beginResetModel()
        if predicate is None:
            self._view = list(self._all_players)
        else:
            self._view = [p for p in self._all_players if predicate(p)]
        if self._sort_col >= 0:
            self._do_sort()
        self.endResetModel()

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
            if col_name in ('name', 'club', 'nationality', 'best_pos',
                            'parent_club', 'league', 'listed_reason'):
                return str(val) if val else ''
            if col_name == 'age':
                return str(val) if val else ''
            if col_name == 'est_value':
                return _format_money(val)
            if col_name == 'wage':
                return _format_money(val)
            if col_name in ('ca', 'pa'):
                return str(val) if val else ''
            if col_name == 'reputation':
                return str(val) if val else ''
            if col_name == 'contract_expiry':
                return _format_fm_date(val) if val else ''
            if col_name in ('transfer_listed', 'loan_listed', 'on_loan'):
                return 'Yes' if val else ''
            if col_name in ('contract_transfer_opts', 'contract_option_years'):
                return str(val) if val else ''
            if col_name in ATTR_COLUMNS:
                return str(val) if val else ''
            if col_name in PERSONALITY_COLS:
                return str(val) if val else ''
            return str(val) if val is not None else ''

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col_name in ('age', 'ca', 'pa', 'reputation', 'est_value',
                            'wage', 'contract_transfer_opts',
                            'contract_option_years'):
                return (Qt.AlignmentFlag.AlignRight
                        | Qt.AlignmentFlag.AlignVCenter)
            if col_name in ATTR_COLUMNS or col_name in PERSONALITY_COLS:
                return (Qt.AlignmentFlag.AlignRight
                        | Qt.AlignmentFlag.AlignVCenter)
            return (Qt.AlignmentFlag.AlignLeft
                    | Qt.AlignmentFlag.AlignVCenter)

        if role == Qt.ItemDataRole.ForegroundRole:
            if col_name in ('ca', 'pa'):
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

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.ItemDataRole.DisplayRole):
        if (orientation == Qt.Orientation.Horizontal
                and role == Qt.ItemDataRole.DisplayRole):
            if 0 <= section < len(TABLE_COLS):
                return COL_HEADERS.get(TABLE_COLS[section], TABLE_COLS[section])
        return None

    def sort(self, column: int,
             order: Qt.SortOrder = Qt.SortOrder.AscendingOrder):
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
                return (0, '')
            if isinstance(v, str):
                return (1, v.lower())
            if isinstance(v, bool):
                return (1 if v else 0, '')
            return (v, '')

        self._view.sort(key=sort_key, reverse=reverse)


# ---------------------------------------------------------------------------
# ScanWorker
# ---------------------------------------------------------------------------

class ScanWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def run(self):
        try:
            self.progress.emit(0, 100, 'Finding FM process…')
            proc = find_fm_process()
            if proc is None:
                self.error.emit(
                    'FM24 process not found. Is the game running?')
                return

            self.progress.emit(10, 100, 'Opening memory reader…')
            reader = MemoryReader(proc.pid)
            reader.open()

            self.progress.emit(20, 100, 'Getting memory regions…')
            regions = get_memory_regions(proc.pid)

            self.progress.emit(30, 100, 'Scanning game data…')
            scanner = GameScanner(reader, regions)
            if not scanner.scan_all():
                self.error.emit('Failed to locate game data structures.')
                reader.close()
                return

            global GAME_YEAR, GAME_DAY
            GAME_YEAR = scanner.pointers.game_date_year
            GAME_DAY = scanner.pointers.game_date_day

            self.progress.emit(50, 100, 'Reading players…')
            player_reader = PlayerReader(reader, scanner)
            players = player_reader.read_all()

            self.progress.emit(70, 100, 'Reading clubs…')
            club_reader = ClubReader(reader, scanner.pointers.dbt_root)
            clubs = club_reader.read_all_clubs()

            self.progress.emit(85, 100, 'Enriching club data…')
            enrich_clubs_with_players(clubs, players, GAME_YEAR)

            reader.close()
            self.progress.emit(100, 100, 'Done!')
            self.finished.emit({'players': players, 'clubs': clubs})

        except Exception as e:
            logger.exception('Scan failed')
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# PositionFilterWidget
# ---------------------------------------------------------------------------

_POS_COORDS = {
    'GK':  (0.50, 0.92),
    'SW':  (0.50, 0.83),
    'DL':  (0.22, 0.78),
    'DC':  (0.50, 0.78),
    'DR':  (0.78, 0.78),
    'WBL': (0.08, 0.68),
    'WBR': (0.92, 0.68),
    'DM':  (0.50, 0.62),
    'ML':  (0.12, 0.48),
    'MC':  (0.50, 0.48),
    'MR':  (0.88, 0.48),
    'AML': (0.22, 0.30),
    'AMC': (0.50, 0.30),
    'AMR': (0.78, 0.30),
    'ST':  (0.50, 0.12),
}

_POS_CYCLE = [0, 10, 15, 20]
_DOT_RADIUS = 14


class PositionFilterWidget(QWidget):
    """Interactive pitch diagram with clickable position dots."""

    values_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(260, 320)
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

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()

        painter.fillRect(0, 0, w, h, QColor(30, 70, 30))

        pen = QPen(QColor(255, 255, 255, 60))
        pen.setWidth(1)
        painter.setPen(pen)
        m = 8
        painter.drawRect(m, m, w - 2 * m, h - 2 * m)
        painter.drawLine(m, h // 2, w - m, h // 2)
        painter.drawEllipse(w // 2 - 25, h // 2 - 25, 50, 50)

        # Penalty areas
        pa_w, pa_h = int(w * 0.40), int(h * 0.12)
        painter.drawRect((w - pa_w) // 2, m, pa_w, pa_h)
        painter.drawRect((w - pa_w) // 2, h - m - pa_h, pa_w, pa_h)

        label_font = QFont()
        label_font.setPixelSize(9)
        label_font.setBold(True)
        value_font = QFont()
        value_font.setPixelSize(10)
        value_font.setBold(True)

        for pos_name, (fx, fy) in _POS_COORDS.items():
            cx = int(fx * w)
            cy = int(fy * h)
            val = self._values.get(pos_name, 0)

            if val >= 20:
                dot_color = QColor(56, 211, 100)
            elif val >= 15:
                dot_color = QColor(31, 111, 235)
            elif val >= 10:
                dot_color = QColor(210, 153, 34)
            else:
                dot_color = QColor(80, 80, 80)

            is_hover = (self._hover_pos == pos_name)
            if is_hover:
                dot_color = dot_color.lighter(130)

            painter.setBrush(QBrush(dot_color))
            painter.setPen(QPen(QColor(255, 255, 255, 180), 1))
            painter.drawEllipse(cx - _DOT_RADIUS, cy - _DOT_RADIUS,
                                _DOT_RADIUS * 2, _DOT_RADIUS * 2)

            painter.setFont(label_font)
            painter.setPen(QColor(255, 255, 255))
            label_rect = QRectF(cx - 20, cy - _DOT_RADIUS - 14, 40, 13)
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter,
                             pos_name)

            if val > 0:
                painter.setFont(value_font)
                painter.setPen(QColor(255, 255, 255))
                val_rect = QRectF(cx - 12, cy - 6, 24, 14)
                painter.drawText(val_rect, Qt.AlignmentFlag.AlignCenter,
                                 str(val))

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
        self._hover_pos = self._hit_test(event.position().x(),
                                         event.position().y())
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


# ---------------------------------------------------------------------------
# SearchDialog
# ---------------------------------------------------------------------------

class SearchDialog(QDialog):
    """Filter dialog with tabs for all attribute categories."""

    def __init__(self, filter_data: dict, current_filters: dict | None = None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle('Player Search')
        self.setMinimumSize(700, 600)
        self.setStyleSheet(SS_WIDGET + SS_DIALOG)

        self._filter_data = filter_data
        self._current = current_filters or {}
        self._attr_spins: dict[str, tuple[QSpinBox, QSpinBox]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        self._build_general_tab()
        self._build_attr_tab('Technical', ATTR_OFFSETS.TECHNICAL_FIELDS)
        self._build_attr_tab('Mental', ATTR_OFFSETS.MENTAL_FIELDS)
        self._build_attr_tab('Physical', ATTR_OFFSETS.PHYSICAL_FIELDS)
        self._build_attr_tab('Goalkeeping', ATTR_OFFSETS.GOALKEEPER_FIELDS)
        self._build_attr_tab('Personality', PERSONALITY_COLS,
                             label_fn=lambda c: c[5:].replace('_', ' ').title())
        self._build_attr_tab('Hidden', ATTR_OFFSETS.HIDDEN_FIELDS)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._restore_from_current()

    # -- General tab -------------------------------------------------------

    def _build_general_tab(self):
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(8, 8, 8, 8)

        # Location hierarchy
        loc_group = QGroupBox('Location')
        loc_layout = QFormLayout(loc_group)
        loc_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self._continent_combo = QComboBox()
        self._continent_combo.addItem('Any')
        for c in sorted(self._filter_data.get('continents', [])):
            self._continent_combo.addItem(c)
        self._continent_combo.currentTextChanged.connect(
            self._on_continent_changed)
        loc_layout.addRow('Continent:', self._continent_combo)

        self._nation_combo = QComboBox()
        self._nation_combo.addItem('Any')
        self._nation_combo.currentTextChanged.connect(
            self._on_nation_changed)
        loc_layout.addRow('Nation:', self._nation_combo)

        self._league_combo = QComboBox()
        self._league_combo.addItem('Any')
        self._league_combo.currentTextChanged.connect(
            self._on_league_changed)
        loc_layout.addRow('League:', self._league_combo)

        self._club_combo = QComboBox()
        self._club_combo.addItem('Any')
        loc_layout.addRow('Club:', self._club_combo)

        outer.addWidget(loc_group)

        # Position filter + ranges side by side
        mid_layout = QHBoxLayout()

        pos_group = QGroupBox('Positions')
        pos_inner = QVBoxLayout(pos_group)
        self._pos_widget = PositionFilterWidget()
        pos_inner.addWidget(self._pos_widget)
        reset_btn = QPushButton('Reset')
        reset_btn.setMaximumWidth(80)
        reset_btn.clicked.connect(self._pos_widget.reset)
        pos_inner.addWidget(reset_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        mid_layout.addWidget(pos_group)

        range_group = QGroupBox('Ranges')
        range_layout = QFormLayout(range_group)
        range_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self._age_min = self._spin(15, 50, 0)
        self._age_max = self._spin(15, 50, 0)
        range_layout.addRow('Age min:', self._age_min)
        range_layout.addRow('Age max:', self._age_max)

        self._ca_min = self._spin(0, 200, 0)
        self._ca_max = self._spin(0, 200, 0)
        range_layout.addRow('CA min:', self._ca_min)
        range_layout.addRow('CA max:', self._ca_max)

        self._pa_min = self._spin(0, 200, 0)
        self._pa_max = self._spin(0, 200, 0)
        range_layout.addRow('PA min:', self._pa_min)
        range_layout.addRow('PA max:', self._pa_max)

        self._rep_min = self._spin(0, 10000, 0, step=100)
        self._rep_max = self._spin(0, 10000, 0, step=100)
        range_layout.addRow('Rep min:', self._rep_min)
        range_layout.addRow('Rep max:', self._rep_max)

        mid_layout.addWidget(range_group)
        outer.addLayout(mid_layout)
        outer.addStretch()

        self._tabs.addTab(tab, 'General')

    def _on_continent_changed(self, text: str):
        self._nation_combo.blockSignals(True)
        self._nation_combo.clear()
        self._nation_combo.addItem('Any')
        if text and text != 'Any':
            nations = self._filter_data.get('nations', {}).get(text, [])
            for n in sorted(nations):
                self._nation_combo.addItem(n)
        self._nation_combo.blockSignals(False)
        self._on_nation_changed(self._nation_combo.currentText())

    def _on_nation_changed(self, text: str):
        self._league_combo.blockSignals(True)
        self._league_combo.clear()
        self._league_combo.addItem('Any')
        if text and text != 'Any':
            leagues = self._filter_data.get('leagues', {}).get(text, [])
            for league_name, rep in leagues:
                self._league_combo.addItem(
                    f'{league_name} ({rep})' if rep else league_name)
        self._league_combo.blockSignals(False)
        self._on_league_changed(self._league_combo.currentText())

    def _on_league_changed(self, text: str):
        self._club_combo.blockSignals(True)
        self._club_combo.clear()
        self._club_combo.addItem('Any')
        if text and text != 'Any':
            league_name = text.rsplit(' (', 1)[0]
            clubs = self._filter_data.get('clubs', {}).get(league_name, [])
            for c in sorted(clubs):
                self._club_combo.addItem(c)
        self._club_combo.blockSignals(False)

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

        hdr_font = QFont()
        hdr_font.setBold(True)
        for col_offset in (0, 4):
            lbl_attr = QLabel('Attribute')
            lbl_attr.setFont(hdr_font)
            lbl_attr.setStyleSheet('color: #8b949e;')
            grid.addWidget(lbl_attr, 0, col_offset)
            lbl_min = QLabel('Min')
            lbl_min.setFont(hdr_font)
            lbl_min.setStyleSheet('color: #8b949e;')
            grid.addWidget(lbl_min, 0, col_offset + 1)
            lbl_max = QLabel('Max')
            lbl_max.setFont(hdr_font)
            lbl_max.setStyleSheet('color: #8b949e;')
            grid.addWidget(lbl_max, 0, col_offset + 2)

        half = (len(fields) + 1) // 2
        for i, field in enumerate(fields):
            if label_fn:
                display = label_fn(field)
            else:
                display = FULL_NAMES.get(field, field.replace('_', ' ').title())
            col_offset = 0 if i < half else 4
            row = (i % half) + 1

            lbl = QLabel(display)
            lbl.setStyleSheet('color: #c9d1d9; font-size: 12px;')
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
        s.setSpecialValueText('-')
        return s

    # -- Restore / collect -------------------------------------------------

    def _restore_from_current(self):
        c = self._current
        if not c:
            return
        if c.get('continent'):
            idx = self._continent_combo.findText(c['continent'])
            if idx >= 0:
                self._continent_combo.setCurrentIndex(idx)
        if c.get('nation'):
            idx = self._nation_combo.findText(c['nation'])
            if idx >= 0:
                self._nation_combo.setCurrentIndex(idx)
        if c.get('league_display'):
            idx = self._league_combo.findText(c['league_display'])
            if idx >= 0:
                self._league_combo.setCurrentIndex(idx)
        if c.get('club'):
            idx = self._club_combo.findText(c['club'])
            if idx >= 0:
                self._club_combo.setCurrentIndex(idx)

        self._age_min.setValue(c.get('age_min', 0))
        self._age_max.setValue(c.get('age_max', 0))
        self._ca_min.setValue(c.get('ca_min', 0))
        self._ca_max.setValue(c.get('ca_max', 0))
        self._pa_min.setValue(c.get('pa_min', 0))
        self._pa_max.setValue(c.get('pa_max', 0))
        self._rep_min.setValue(c.get('rep_min', 0))
        self._rep_max.setValue(c.get('rep_max', 0))

        self._pos_widget.set_values(c.get('positions', {}))

        for attr, (smin, smax) in self._attr_spins.items():
            bounds = c.get('attrs', {}).get(attr)
            if bounds:
                smin.setValue(bounds[0])
                smax.setValue(bounds[1])

    def get_filters(self) -> dict:
        f: dict = {}

        continent = self._continent_combo.currentText()
        if continent and continent != 'Any':
            f['continent'] = continent

        nation = self._nation_combo.currentText()
        if nation and nation != 'Any':
            f['nation'] = nation

        league_text = self._league_combo.currentText()
        if league_text and league_text != 'Any':
            f['league_display'] = league_text
            f['league'] = league_text.rsplit(' (', 1)[0]

        club = self._club_combo.currentText()
        if club and club != 'Any':
            f['club'] = club

        if self._age_min.value() > self._age_min.minimum():
            f['age_min'] = self._age_min.value()
        if self._age_max.value() > self._age_max.minimum():
            f['age_max'] = self._age_max.value()
        if self._ca_min.value() > 0:
            f['ca_min'] = self._ca_min.value()
        if self._ca_max.value() > 0:
            f['ca_max'] = self._ca_max.value()
        if self._pa_min.value() > 0:
            f['pa_min'] = self._pa_min.value()
        if self._pa_max.value() > 0:
            f['pa_max'] = self._pa_max.value()
        if self._rep_min.value() > 0:
            f['rep_min'] = self._rep_min.value()
        if self._rep_max.value() > 0:
            f['rep_max'] = self._rep_max.value()

        pos = self._pos_widget.get_values()
        if pos:
            f['positions'] = pos

        attrs: dict[str, tuple[int, int]] = {}
        for attr, (smin, smax) in self._attr_spins.items():
            lo = smin.value()
            hi = smax.value()
            if lo > 0 or hi > 0:
                attrs[attr] = (lo, hi)
        if attrs:
            f['attrs'] = attrs

        return f


# ---------------------------------------------------------------------------
# PlayerDetailDialog
# ---------------------------------------------------------------------------

class PlayerDetailDialog(QDialog):
    """Full player information dialog shown on double-click."""

    def __init__(self, player, parent=None):
        super().__init__(parent)
        self.setWindowTitle(getattr(player, 'display_name', '') or 'Player')
        self.setMinimumSize(680, 620)
        self.setStyleSheet(SS_WIDGET + SS_DIALOG)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        layout.addWidget(self._build_header(player))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 8, 0, 0)

        content_layout.addWidget(self._build_stats_row(player))

        contract_w = self._build_contract_info(player)
        if contract_w:
            content_layout.addWidget(contract_w)

        content_layout.addWidget(self._section_label('Attributes'))
        content_layout.addWidget(self._build_attribute_grid(player))

        content_layout.addWidget(self._section_label('Positions'))
        content_layout.addWidget(self._build_positions(player))

        pers_w = self._build_personality(player)
        if pers_w:
            content_layout.addWidget(self._section_label('Personality'))
            content_layout.addWidget(pers_w)

        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)

    def _build_header(self, player) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 8)

        name_lbl = QLabel(getattr(player, 'display_name', ''))
        name_font = QFont()
        name_font.setPointSize(18)
        name_font.setBold(True)
        name_lbl.setFont(name_font)
        name_lbl.setStyleSheet('color: #f0f6fc;')
        lay.addWidget(name_lbl)

        parts = []
        if player.club:
            parts.append(player.club)
        if player.nationality:
            parts.append(player.nationality)
        if parts:
            sub_lbl = QLabel(' · '.join(parts))
            sub_lbl.setStyleSheet('color: #8b949e; font-size: 13px;')
            lay.addWidget(sub_lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet('color: #21262d;')
        lay.addWidget(sep)
        return w

    def _build_stats_row(self, player) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 4)

        age = _player_age(player)
        value = _estimated_player_value(player)
        wage = getattr(player, 'wage', 0) or 0
        ca = player.current_ability
        pa = player.potential_ability
        rep = player.reputation or 0

        stats = [
            ('Age', str(age) if age else '-'),
            ('CA', str(ca)),
            ('PA', str(pa)),
            ('Rep', str(rep)),
            ('Value', _format_money(value)),
            ('Wage', _format_money(wage)),
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
        if getattr(player, 'on_loan', False):
            parent = getattr(player, 'parent_club', '')
            if parent:
                parts.append(f'On Loan from: {parent}')
            else:
                parts.append('On Loan')
        if getattr(player, 'transfer_listed', False):
            parts.append('Transfer Listed')
        if getattr(player, 'loan_listed', False):
            parts.append('Loan Listed')

        expiry = getattr(player, 'contract_expiry', 0)
        if expiry:
            parts.append(f'Contract expires: {_format_fm_date(expiry)}')

        opt_years = getattr(player, 'contract_option_years', 0)
        if opt_years:
            parts.append(f'Option years: {opt_years}')

        league = getattr(player, 'league', '')
        if league:
            parts.append(f'League: {league}')

        if not parts:
            return None

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 4)
        for line in parts:
            lbl = QLabel(line)
            lbl.setStyleSheet('color: #c9d1d9; font-size: 12px;')
            lay.addWidget(lbl)
        return w

    def _build_attribute_grid(self, player) -> QWidget:
        w = QWidget()
        master_lay = QHBoxLayout(w)
        master_lay.setContentsMargins(0, 0, 0, 0)
        master_lay.setSpacing(16)

        sections = [
            ('Technical', ATTR_OFFSETS.TECHNICAL_FIELDS),
            ('Mental', ATTR_OFFSETS.MENTAL_FIELDS),
            ('Physical', ATTR_OFFSETS.PHYSICAL_FIELDS),
            ('Goalkeeping', ATTR_OFFSETS.GOALKEEPER_FIELDS),
        ]
        for section_name, fields in sections:
            col_w = QWidget()
            col_lay = QVBoxLayout(col_w)
            col_lay.setContentsMargins(0, 0, 0, 0)
            col_lay.setSpacing(1)

            hdr = QLabel(section_name)
            hdr.setStyleSheet(
                'color: #8b949e; font-size: 11px; font-weight: 600;')
            col_lay.addWidget(hdr)

            for field in fields:
                val = getattr(player, field, 0) or 0
                display = FULL_NAMES.get(field, field)
                color = attr_color_hex(val) if val > 0 else '#484f58'
                row = QWidget()
                row_lay = QHBoxLayout(row)
                row_lay.setContentsMargins(0, 0, 0, 0)
                row_lay.setSpacing(4)
                name_lbl = QLabel(display)
                name_lbl.setStyleSheet(
                    'color: #c9d1d9; font-size: 11px;')
                name_lbl.setMinimumWidth(100)
                val_lbl = QLabel(str(val) if val else '-')
                val_lbl.setStyleSheet(
                    f'color: {color}; font-size: 12px; font-weight: 600;')
                val_lbl.setFixedWidth(24)
                val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
                row_lay.addWidget(name_lbl)
                row_lay.addWidget(val_lbl)
                col_lay.addWidget(row)

            col_lay.addStretch()
            master_lay.addWidget(col_w)

        master_lay.addStretch()
        return w

    def _build_positions(self, player) -> QWidget:
        w = QWidget()
        lay = QGridLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        positions = getattr(player, 'positions', {}) or {}
        col = 0
        row = 0
        for pos_name in POSITION_NAMES:
            val = positions.get(pos_name, 0)
            if val <= 0:
                continue
            color = attr_color_hex(val)
            lbl = QLabel(
                f"<span style='color:#8b949e;'>{pos_name}:</span> "
                f"<span style='color:{color}; font-weight:600;'>{val}</span>"
            )
            lbl.setStyleSheet('font-size: 12px;')
            lay.addWidget(lbl, row, col)
            col += 1
            if col >= 5:
                col = 0
                row += 1

        return w

    def _build_personality(self, player) -> QWidget | None:
        has_any = False
        for pc in PERSONALITY_COLS:
            if getattr(player, pc, 0):
                has_any = True
                break
        if not has_any:
            return None

        w = QWidget()
        lay = QGridLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        col = 0
        row = 0
        for pc in PERSONALITY_COLS:
            val = getattr(player, pc, 0) or 0
            display = pc[5:].replace('_', ' ').title()
            color = attr_color_hex(val) if val > 0 else '#484f58'
            lbl = QLabel(
                f"<span style='color:#8b949e;'>{display}:</span> "
                f"<span style='color:{color}; font-weight:600;'>"
                f"{val if val else '-'}</span>"
            )
            lbl.setStyleSheet('font-size: 12px;')
            lay.addWidget(lbl, row, col)
            col += 1
            if col >= 4:
                col = 0
                row += 1

        return w

    @staticmethod
    def _section_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            'color: #f0f6fc; font-size: 13px; font-weight: 600; '
            'padding: 8px 0 2px 0;'
        )
        return lbl


# ---------------------------------------------------------------------------
# MainWindow
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle('FM Scout')
        self.resize(1400, 860)
        self.setStyleSheet(SS_WIDGET)

        self._scan_worker: Optional[ScanWorker] = None
        self._active_filters: dict = {}
        self._shortlist_uids: set[int] = set()
        self._hidden_cols: set[str] = set(DEFAULT_HIDDEN_COLS)
        self._all_players: list = []
        self._all_clubs: list = []

        self._filter_continents: list[str] = []
        self._filter_nations: dict[str, list[str]] = {}
        self._filter_leagues: dict[str, list[tuple[str, int]]] = {}
        self._filter_clubs: dict[str, list[str]] = {}

        self._build_ui()
        self._restore_column_layout()
        self._apply_column_visibility()

    # -- UI construction ---------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Top bar
        top_bar = QHBoxLayout()
        self._scan_btn = QPushButton('Scan Players')
        self._scan_btn.setObjectName('primary')
        self._scan_btn.clicked.connect(self._start_scan)
        top_bar.addWidget(self._scan_btn)

        self._refresh_btn = QPushButton('Refresh')
        self._refresh_btn.clicked.connect(self._start_scan)
        self._refresh_btn.setVisible(False)
        top_bar.addWidget(self._refresh_btn)

        self._count_label = QLabel('')
        self._count_label.setStyleSheet(
            'color: #f0f6fc; font-size: 13px; font-weight: 600;')
        top_bar.addWidget(self._count_label)
        top_bar.addStretch()
        root.addLayout(top_bar)

        # Tab widget
        self._tab_widget = QTabWidget()
        root.addWidget(self._tab_widget)

        self._build_search_tab()
        self._build_shortlist_tab()

        self._tactics_widget = TacticsBuilderWidget()
        self._tab_widget.addTab(self._tactics_widget, 'Tactics')

        self._club_widget = ClubViewerWidget()
        self._tab_widget.addTab(self._club_widget, 'Clubs')

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        self._progress_bar.setMaximumWidth(300)
        self._status_bar.addPermanentWidget(self._progress_bar)

        # Hide post-scan widgets
        self._post_scan_widgets = [
            self._refresh_btn, self._search_toolbar,
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

        filter_btn = QPushButton('Filter')
        filter_btn.clicked.connect(self._open_search_dialog)
        tbar.addWidget(filter_btn)

        clear_btn = QPushButton('Clear')
        clear_btn.clicked.connect(self._clear_filters)
        tbar.addWidget(clear_btn)

        add_sl_btn = QPushButton('Add to Shortlist')
        add_sl_btn.clicked.connect(self._add_to_shortlist)
        tbar.addWidget(add_sl_btn)

        export_btn = QPushButton('Export CSV')
        export_btn.clicked.connect(self._export_search_csv)
        tbar.addWidget(export_btn)

        tbar.addStretch()

        self._filter_label = QLabel('')
        self._filter_label.setStyleSheet(
            'color: #58a6ff; font-size: 11px;')
        tbar.addWidget(self._filter_label)

        lay.addWidget(self._search_toolbar)

        self._search_model = PlayerTableModel(self)
        self._search_table = QTableView()
        self._search_table.setModel(self._search_model)
        self._search_table.setStyleSheet(SS_TABLE)
        self._search_table.setSortingEnabled(True)
        self._search_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._search_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self._search_table.verticalHeader().setVisible(False)
        self._search_table.horizontalHeader().setStretchLastSection(True)
        self._search_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive)
        self._search_table.doubleClicked.connect(self._on_search_double_click)

        self._name_delegate = NameBadgeDelegate(
            self._search_table, self._search_model)
        self._search_table.setItemDelegateForColumn(0, self._name_delegate)

        hdr = self._search_table.horizontalHeader()
        hdr.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        hdr.customContextMenuRequested.connect(self._show_column_menu)

        lay.addWidget(self._search_table)
        self._tab_widget.addTab(tab, 'Search')

    def _build_shortlist_tab(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(0, 0, 0, 0)

        self._shortlist_toolbar = QWidget()
        tbar = QHBoxLayout(self._shortlist_toolbar)
        tbar.setContentsMargins(0, 4, 0, 4)

        remove_btn = QPushButton('Remove')
        remove_btn.clicked.connect(self._remove_from_shortlist)
        tbar.addWidget(remove_btn)

        save_btn = QPushButton('Save')
        save_btn.clicked.connect(self._export_shortlist)
        tbar.addWidget(save_btn)

        load_btn = QPushButton('Load')
        load_btn.clicked.connect(self._import_shortlist)
        tbar.addWidget(load_btn)

        tbar.addStretch()

        self._shortlist_count = QLabel('')
        self._shortlist_count.setStyleSheet(
            'color: #8b949e; font-size: 11px;')
        tbar.addWidget(self._shortlist_count)

        lay.addWidget(self._shortlist_toolbar)

        self._shortlist_model = PlayerTableModel(self)
        self._shortlist_table = QTableView()
        self._shortlist_table.setModel(self._shortlist_model)
        self._shortlist_table.setStyleSheet(SS_TABLE)
        self._shortlist_table.setSortingEnabled(True)
        self._shortlist_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._shortlist_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self._shortlist_table.verticalHeader().setVisible(False)
        self._shortlist_table.horizontalHeader().setStretchLastSection(True)
        self._shortlist_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive)
        self._shortlist_table.doubleClicked.connect(
            self._on_shortlist_double_click)

        self._sl_name_delegate = NameBadgeDelegate(
            self._shortlist_table, self._shortlist_model)
        self._shortlist_table.setItemDelegateForColumn(
            0, self._sl_name_delegate)

        sl_hdr = self._shortlist_table.horizontalHeader()
        sl_hdr.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        sl_hdr.customContextMenuRequested.connect(self._show_column_menu)

        lay.addWidget(self._shortlist_table)
        self._tab_widget.addTab(tab, 'Shortlist')

    # -- Scanning ----------------------------------------------------------

    def _start_scan(self):
        if self._scan_worker and self._scan_worker.isRunning():
            return

        self._scan_btn.setEnabled(False)
        self._refresh_btn.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)
        self._status_bar.showMessage('Scanning…')

        self._scan_worker = ScanWorker()
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.finished.connect(self._on_scan_done)
        self._scan_worker.error.connect(self._on_scan_error)
        self._scan_worker.start()

    def _on_scan_progress(self, current: int, total: int, msg: str):
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(current)
        self._status_bar.showMessage(msg)

    def _on_scan_done(self, result: dict):
        players = result.get('players', [])
        clubs = result.get('clubs', [])

        self._all_players = players
        self._all_clubs = clubs

        self._search_model.set_all_players(players)
        self._count_label.setText(f'{len(players):,} players')
        self._apply_column_visibility()

        self._rebuild_shortlist_model()
        self._rebuild_filter_options()

        my_club = None
        if clubs:
            top_clubs = sorted(clubs, key=lambda c: c.reputation,
                               reverse=True)
            if top_clubs:
                my_club = top_clubs[0]

        if hasattr(self._tactics_widget, 'set_data'):
            try:
                self._tactics_widget.set_data(
                    my_club=my_club, players=players)
            except Exception:
                logger.debug('Tactics widget set_data not available yet')

        self._club_widget.set_clubs(clubs, players, GAME_YEAR or 2024)

        self._scan_btn.setEnabled(True)
        self._refresh_btn.setEnabled(True)
        self._progress_bar.setVisible(False)
        for w in self._post_scan_widgets:
            w.setVisible(True)

        self._status_bar.showMessage(
            f'Scan complete – {len(players):,} players, '
            f'{len(clubs):,} clubs', 5000)

        if self._active_filters:
            self._apply_active_filters()

    def _on_scan_error(self, msg: str):
        self._scan_btn.setEnabled(True)
        self._refresh_btn.setEnabled(True)
        self._progress_bar.setVisible(False)
        self._status_bar.showMessage(f'Error: {msg}', 10000)
        QMessageBox.critical(self, 'Scan Error', msg)

    # -- Column management -------------------------------------------------

    def _show_column_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet(SS_DIALOG)

        default_action = menu.addAction('Show Default Columns Only')
        default_action.setData('__reset__')
        menu.addSeparator()

        sub_contract = menu.addMenu('Contract / Status')
        for col in CONTRACT_EXTRA_COLS:
            act = sub_contract.addAction(MENU_HEADERS.get(col, col))
            act.setCheckable(True)
            act.setChecked(col not in self._hidden_cols)
            act.setData(col)

        sub_tech = menu.addMenu('Technical')
        for field in ATTR_OFFSETS.TECHNICAL_FIELDS:
            act = sub_tech.addAction(MENU_HEADERS.get(field, field))
            act.setCheckable(True)
            act.setChecked(field not in self._hidden_cols)
            act.setData(field)

        sub_mental = menu.addMenu('Mental')
        for field in ATTR_OFFSETS.MENTAL_FIELDS:
            act = sub_mental.addAction(MENU_HEADERS.get(field, field))
            act.setCheckable(True)
            act.setChecked(field not in self._hidden_cols)
            act.setData(field)

        sub_phys = menu.addMenu('Physical')
        for field in ATTR_OFFSETS.PHYSICAL_FIELDS:
            act = sub_phys.addAction(MENU_HEADERS.get(field, field))
            act.setCheckable(True)
            act.setChecked(field not in self._hidden_cols)
            act.setData(field)

        sub_gk = menu.addMenu('Goalkeeping')
        for field in ATTR_OFFSETS.GOALKEEPER_FIELDS:
            act = sub_gk.addAction(MENU_HEADERS.get(field, field))
            act.setCheckable(True)
            act.setChecked(field not in self._hidden_cols)
            act.setData(field)

        sub_hidden = menu.addMenu('Hidden')
        for field in ATTR_OFFSETS.HIDDEN_FIELDS:
            act = sub_hidden.addAction(MENU_HEADERS.get(field, field))
            act.setCheckable(True)
            act.setChecked(field not in self._hidden_cols)
            act.setData(field)

        sub_pers = menu.addMenu('Personality')
        for pc in PERSONALITY_COLS:
            act = sub_pers.addAction(MENU_HEADERS.get(pc, pc))
            act.setCheckable(True)
            act.setChecked(pc not in self._hidden_cols)
            act.setData(pc)

        chosen = menu.exec(
            self._search_table.horizontalHeader().mapToGlobal(pos))
        if chosen is None:
            return

        col_data = chosen.data()
        if col_data == '__reset__':
            self._hidden_cols = set(DEFAULT_HIDDEN_COLS)
        elif col_data:
            if col_data in self._hidden_cols:
                self._hidden_cols.discard(col_data)
            else:
                self._hidden_cols.add(col_data)

        self._apply_column_visibility()
        self._save_column_layout()

    def _apply_column_visibility(self):
        for i, col_name in enumerate(TABLE_COLS):
            hidden = col_name in self._hidden_cols
            self._search_table.setColumnHidden(i, hidden)
            self._shortlist_table.setColumnHidden(i, hidden)

        name_idx = COL_INDEX.get('name', 0)
        self._search_table.setColumnWidth(name_idx, 200)
        self._shortlist_table.setColumnWidth(name_idx, 200)

        club_idx = COL_INDEX.get('club', -1)
        if club_idx >= 0:
            self._search_table.setColumnWidth(club_idx, 140)
            self._shortlist_table.setColumnWidth(club_idx, 140)

        nat_idx = COL_INDEX.get('nationality', -1)
        if nat_idx >= 0:
            self._search_table.setColumnWidth(nat_idx, 100)
            self._shortlist_table.setColumnWidth(nat_idx, 100)

        for i, col_name in enumerate(TABLE_COLS):
            if col_name in ATTR_COLUMNS or col_name in PERSONALITY_COLS:
                self._search_table.setColumnWidth(i, 38)
                self._shortlist_table.setColumnWidth(i, 38)

    def _save_column_layout(self):
        settings = QSettings('FMScout', 'FMScout')
        settings.setValue('table_layout_version', TABLE_LAYOUT_VERSION)
        settings.setValue('hidden_columns', list(self._hidden_cols))

    def _restore_column_layout(self):
        settings = QSettings('FMScout', 'FMScout')
        version = settings.value('table_layout_version', 0, type=int)
        if version != TABLE_LAYOUT_VERSION:
            return
        hidden = settings.value('hidden_columns', None)
        if hidden is not None:
            self._hidden_cols = set(hidden)

    # -- Filter system -----------------------------------------------------

    def _rebuild_filter_options(self):
        continents: set[str] = set()
        nations_by_continent: dict[str, set[str]] = {}
        leagues_by_nation: dict[str, dict[str, int]] = {}
        clubs_by_league: dict[str, set[str]] = {}

        for p in self._all_players:
            continent = getattr(p, 'league_continent', '') or ''
            nation = getattr(p, 'nationality', '') or ''
            league = getattr(p, 'league', '') or ''
            club = getattr(p, 'club', '') or ''
            rep = getattr(p, 'reputation', 0) or 0

            if continent:
                continents.add(continent)
                if continent not in nations_by_continent:
                    nations_by_continent[continent] = set()
                if nation:
                    nations_by_continent[continent].add(nation)

            if nation and league:
                if nation not in leagues_by_nation:
                    leagues_by_nation[nation] = {}
                if league not in leagues_by_nation[nation]:
                    leagues_by_nation[nation][league] = 0
                if rep > leagues_by_nation[nation][league]:
                    leagues_by_nation[nation][league] = rep

            if league and club:
                if league not in clubs_by_league:
                    clubs_by_league[league] = set()
                clubs_by_league[league].add(club)

        self._filter_continents = sorted(continents)
        self._filter_nations = {
            k: sorted(v) for k, v in nations_by_continent.items()
        }

        self._filter_leagues = {}
        for nation, leagues in leagues_by_nation.items():
            league_list = [(name, rep) for name, rep in leagues.items()]
            league_list.sort(key=lambda x: x[1], reverse=True)
            self._filter_leagues[nation] = league_list

        self._filter_clubs = {
            k: sorted(v) for k, v in clubs_by_league.items()
        }

    def _open_search_dialog(self):
        filter_data = {
            'continents': self._filter_continents,
            'nations': self._filter_nations,
            'leagues': self._filter_leagues,
            'clubs': self._filter_clubs,
        }
        dlg = SearchDialog(filter_data, self._active_filters, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._active_filters = dlg.get_filters()
            self._apply_active_filters()

    def _apply_active_filters(self):
        f = self._active_filters
        if not f:
            self._search_model.filter()
            self._filter_label.setText('')
            return

        def predicate(player) -> bool:
            if f.get('continent'):
                pc = getattr(player, 'league_continent', '') or ''
                if pc != f['continent']:
                    return False

            if f.get('nation'):
                if (getattr(player, 'nationality', '') or '') != f['nation']:
                    return False

            if f.get('league'):
                if (getattr(player, 'league', '') or '') != f['league']:
                    return False

            if f.get('club'):
                if (getattr(player, 'club', '') or '') != f['club']:
                    return False

            age = _player_age(player)
            if f.get('age_min') and age < f['age_min']:
                return False
            if f.get('age_max') and age > f['age_max']:
                return False

            ca = player.current_ability
            if f.get('ca_min') and ca < f['ca_min']:
                return False
            if f.get('ca_max') and ca > f['ca_max']:
                return False

            pa = player.potential_ability
            if f.get('pa_min') and pa < f['pa_min']:
                return False
            if f.get('pa_max') and pa > f['pa_max']:
                return False

            rep = player.reputation or 0
            if f.get('rep_min') and rep < f['rep_min']:
                return False
            if f.get('rep_max') and rep > f['rep_max']:
                return False

            pos_filters = f.get('positions', {})
            if pos_filters:
                positions = getattr(player, 'positions', {}) or {}
                for pos, min_val in pos_filters.items():
                    if min_val > 0:
                        player_val = positions.get(pos, 0)
                        if player_val < min_val:
                            return False

            attr_filters = f.get('attrs', {})
            for attr, (amin, amax) in attr_filters.items():
                val = getattr(player, attr, 0) or 0
                if amin > 0 and val < amin:
                    return False
                if amax > 0 and val > amax:
                    return False

            return True

        self._search_model.filter(predicate)

        parts = []
        if f.get('continent'):
            parts.append(f['continent'])
        if f.get('nation'):
            parts.append(f['nation'])
        if f.get('league'):
            parts.append(f['league'])
        if f.get('club'):
            parts.append(f['club'])
        n = len(self._search_model.get_view_players())
        desc = ' › '.join(parts) if parts else 'Custom filter'
        self._filter_label.setText(f'{desc} ({n:,} results)')

    def _clear_filters(self):
        self._active_filters = {}
        self._search_model.filter()
        self._filter_label.setText('')

    # -- Shortlist ---------------------------------------------------------

    def _add_to_shortlist(self):
        indexes = self._search_table.selectionModel().selectedRows()
        if not indexes:
            return
        added = 0
        for idx in indexes:
            player = self._search_model.get_player(idx.row())
            if player and hasattr(player, 'uid') and player.uid:
                if player.uid not in self._shortlist_uids:
                    self._shortlist_uids.add(player.uid)
                    added += 1
        if added:
            self._rebuild_shortlist_model()
            self._status_bar.showMessage(
                f'Added {added} player(s) to shortlist', 3000)

    def _remove_from_shortlist(self):
        indexes = self._shortlist_table.selectionModel().selectedRows()
        if not indexes:
            return
        removed = 0
        for idx in indexes:
            player = self._shortlist_model.get_player(idx.row())
            if player and hasattr(player, 'uid') and player.uid:
                self._shortlist_uids.discard(player.uid)
                removed += 1
        if removed:
            self._rebuild_shortlist_model()
            self._status_bar.showMessage(
                f'Removed {removed} player(s) from shortlist', 3000)

    def _rebuild_shortlist_model(self):
        if not self._shortlist_uids:
            self._shortlist_model.set_all_players([])
            self._shortlist_count.setText('')
            return

        shortlisted = [
            p for p in self._all_players
            if hasattr(p, 'uid') and p.uid in self._shortlist_uids
        ]
        self._shortlist_model.set_all_players(shortlisted)
        self._apply_column_visibility()
        self._shortlist_count.setText(f'{len(shortlisted)} players')

    def _export_shortlist(self):
        path, _ = QFileDialog.getSaveFileName(
            self, 'Save Shortlist', '', 'CSV Files (*.csv)')
        if not path:
            return

        players = self._shortlist_model.get_all_players()
        try:
            with open(path, 'w', newline='', encoding='utf-8') as fh:
                writer = csv.writer(fh)
                writer.writerow([
                    'UID', 'Name', 'Club', 'Position', 'CA', 'PA', 'Age',
                    'Nationality', 'Value',
                ])
                for p in players:
                    writer.writerow([
                        p.uid,
                        getattr(p, 'display_name', ''),
                        getattr(p, 'club', ''),
                        getattr(p, 'best_position', ''),
                        p.current_ability,
                        p.potential_ability,
                        _player_age(p),
                        getattr(p, 'nationality', ''),
                        _estimated_player_value(p),
                    ])
            self._status_bar.showMessage(
                f'Saved {len(players)} players to {path}', 5000)
        except OSError as e:
            QMessageBox.warning(self, 'Export Error', str(e))

    def _import_shortlist(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Load Shortlist', '', 'CSV Files (*.csv)')
        if not path:
            return

        try:
            with open(path, 'r', encoding='utf-8') as fh:
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
            self._status_bar.showMessage(
                f'Loaded shortlist: {added} new player(s) added', 5000)
        except OSError as e:
            QMessageBox.warning(self, 'Import Error', str(e))

    def _export_search_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, 'Export Players', '', 'CSV Files (*.csv)')
        if not path:
            return

        players = self._search_model.get_view_players()
        visible_cols = [
            c for c in TABLE_COLS if c not in self._hidden_cols
        ]
        try:
            with open(path, 'w', newline='', encoding='utf-8') as fh:
                writer = csv.writer(fh)
                writer.writerow([
                    MENU_HEADERS.get(c, c) for c in visible_cols
                ])
                for p in players:
                    row_data = []
                    for col in visible_cols:
                        val = _col_value(p, col)
                        if col == 'est_value':
                            row_data.append(_estimated_player_value(p))
                        elif col == 'wage':
                            row_data.append(getattr(p, 'wage', 0) or 0)
                        elif col == 'contract_expiry':
                            row_data.append(
                                _format_fm_date(val) if val else '')
                        elif col in ('transfer_listed', 'loan_listed',
                                     'on_loan'):
                            row_data.append('Yes' if val else '')
                        else:
                            row_data.append(
                                val if val is not None else '')
                    writer.writerow(row_data)

            self._status_bar.showMessage(
                f'Exported {len(players)} players to {path}', 5000)
        except OSError as e:
            QMessageBox.warning(self, 'Export Error', str(e))

    # -- Double click detail -----------------------------------------------

    def _on_search_double_click(self, index: QModelIndex):
        player = self._search_model.get_player(index.row())
        if player:
            dlg = PlayerDetailDialog(player, parent=self)
            dlg.exec()

    def _on_shortlist_double_click(self, index: QModelIndex):
        player = self._shortlist_model.get_player(index.row())
        if player:
            dlg = PlayerDetailDialog(player, parent=self)
            dlg.exec()

    # -- Close event -------------------------------------------------------

    def closeEvent(self, event):
        self._save_column_layout()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

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
    palette.setColor(QPalette.ColorRole.HighlightedText,
                     QColor(240, 246, 252))
    palette.setColor(QPalette.ColorRole.Link, QColor(88, 166, 255))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(22, 27, 34))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(201, 209, 217))
    palette.setColor(QPalette.ColorRole.PlaceholderText,
                     QColor(110, 118, 129))
    palette.setColor(QPalette.ColorRole.Mid, QColor(48, 54, 61))
    palette.setColor(QPalette.ColorRole.Dark, QColor(13, 17, 23))
    palette.setColor(QPalette.ColorRole.Shadow, QColor(1, 4, 9))
    app.setPalette(palette)

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
