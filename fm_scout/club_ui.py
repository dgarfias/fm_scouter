"""Club viewer UI for FM Scout – table, filtering, detail dialog."""

from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, QTimer, QEvent
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QTableView, QHeaderView, QAbstractItemView, QMenu,
    QDialog, QScrollArea, QFrame, QGridLayout,
)

from .club import Club

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

SS_WIDGET = """
QWidget {
    background-color: #0d1117;
    color: #c9d1d9;
}
QLineEdit {
    background-color: #161b22;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}
QLineEdit:focus {
    border-color: #1f6feb;
}
QLabel {
    color: #8b949e;
    font-size: 11px;
}
"""

ALL_COLUMNS: list[tuple[str, str, int]] = [
    ("name",           "Club",         220),
    ("short_name",     "Short Name",   140),
    ("nation",         "Nation",       100),
    ("league",         "League",       160),
    ("continent",      "Continent",     90),
    ("reputation",     "Rep",           60),
    ("club_ability",   "Ability",       60),
    ("club_potential",  "Potential",     60),
    ("squad_size",     "Squad",         50),
    ("avg_ca",         "Avg CA",        60),
    ("best_ca",        "Best CA",       60),
    ("avg_age",        "Avg Age",       60),
]

_DEFAULT_VISIBLE = {"name", "nation", "league", "reputation",
                    "club_ability", "club_potential", "squad_size"}


def _rep_color(value: int) -> QColor | None:
    if value >= 9000:
        return QColor("#3fb950")
    if value >= 7000:
        return QColor("#56d364")
    if value >= 5000:
        return QColor("#c9d1d9")
    if value >= 3000:
        return QColor("#d29922")
    if value > 0:
        return QColor("#f85149")
    return None


def _ca_color(value: float) -> QColor | None:
    v = int(value)
    if v >= 160:
        return QColor("#3fb950")
    if v >= 130:
        return QColor("#56d364")
    if v >= 100:
        return QColor("#c9d1d9")
    if v >= 70:
        return QColor("#d29922")
    if v > 0:
        return QColor("#f85149")
    return None


class ClubTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._clubs: list[Club] = []
        self._filtered: list[Club] = []
        self._visible_cols: list[int] = []
        self._sort_col: int = -1
        self._sort_order: Qt.SortOrder = Qt.SortOrder.AscendingOrder
        self._filter_text: str = ""
        self._hover_row: int = -1
        self._set_visible_columns(_DEFAULT_VISIBLE)

    def _set_visible_columns(self, visible: set[str]):
        self._visible_cols = [
            i for i, (key, _, _) in enumerate(ALL_COLUMNS) if key in visible
        ]

    def set_visible(self, visible: set[str]):
        self.beginResetModel()
        self._set_visible_columns(visible)
        self.endResetModel()

    def set_clubs(self, clubs: list[Club]):
        self.beginResetModel()
        self._clubs = clubs
        self._apply_filter()
        self._hover_row = -1
        self.endResetModel()

    def filter_by_name(self, text: str):
        self.beginResetModel()
        self._filter_text = text.strip().lower()
        self._apply_filter()
        self._hover_row = -1
        self.endResetModel()

    def set_hover_row(self, row: int):
        new_row = row if 0 <= row < len(self._filtered) else -1
        if new_row == self._hover_row:
            return
        old_row = self._hover_row
        self._hover_row = new_row
        self._emit_hover_row_change(old_row)
        self._emit_hover_row_change(new_row)

    def clear_hover_row(self):
        self.set_hover_row(-1)

    def _emit_hover_row_change(self, row: int):
        if row < 0 or row >= len(self._filtered) or not self._visible_cols:
            return
        left = self.index(row, 0)
        right = self.index(row, len(self._visible_cols) - 1)
        self.dataChanged.emit(left, right, [Qt.ItemDataRole.BackgroundRole])

    def _apply_filter(self):
        if not self._filter_text:
            self._filtered = list(self._clubs)
        else:
            t = self._filter_text
            self._filtered = [
                c for c in self._clubs
                if t in c.name.lower() or t in c.short_name.lower()
                or t in c.nation.lower() or t in c.league.lower()
            ]
        if self._sort_col >= 0:
            self._do_sort()

    def _col_key(self, idx: int):
        return ALL_COLUMNS[idx][0]

    def _get_value(self, club: Club, col_idx: int):
        return getattr(club, self._col_key(col_idx), "")

    def rowCount(self, parent=QModelIndex()):
        return len(self._filtered)

    def columnCount(self, parent=QModelIndex()):
        return len(self._visible_cols)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        club = self._filtered[index.row()]
        real_col = self._visible_cols[index.column()]
        key = ALL_COLUMNS[real_col][0]
        value = getattr(club, key, "")

        if role == Qt.ItemDataRole.DisplayRole:
            if key in ("club_ability", "club_potential", "avg_ca"):
                return f"{value:.1f}" if value else ""
            if key == "avg_age":
                return f"{value:.1f}" if value else ""
            if key == "reputation":
                return str(value) if value else ""
            return str(value) if value else ""

        if role == Qt.ItemDataRole.ForegroundRole:
            if key == "reputation" and isinstance(value, (int, float)):
                c = _rep_color(int(value))
                if c:
                    return c
            if key in ("club_ability", "club_potential", "avg_ca", "best_ca"):
                c = _ca_color(float(value) if value else 0)
                if c:
                    return c

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if key in ("reputation", "club_ability", "club_potential",
                       "squad_size", "avg_ca", "best_ca", "avg_age"):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        if role == Qt.ItemDataRole.BackgroundRole:
            if index.row() == self._hover_row:
                return QColor("#161b22")

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            real_col = self._visible_cols[section]
            return ALL_COLUMNS[real_col][1]
        return None

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder):
        self.beginResetModel()
        self._sort_col = self._visible_cols[column] if column < len(self._visible_cols) else -1
        self._sort_order = order
        self._do_sort()
        self.endResetModel()

    def _do_sort(self):
        if self._sort_col < 0:
            return
        key = ALL_COLUMNS[self._sort_col][0]
        reverse = self._sort_order == Qt.SortOrder.DescendingOrder

        def sort_key(c: Club):
            v = getattr(c, key, "")
            if isinstance(v, str):
                return v.lower()
            return v

        self._filtered.sort(key=sort_key, reverse=reverse)

    def club_at(self, row: int) -> Club | None:
        if 0 <= row < len(self._filtered):
            return self._filtered[row]
        return None


class ClubDetailDialog(QDialog):
    def __init__(self, club: Club, players: list, game_year: int = 2024,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(club.display_name)
        self.setMinimumSize(600, 500)
        self.setStyleSheet(SS_WIDGET)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        header = self._build_header(club)
        layout.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; }")
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 8, 0, 0)

        current_squad = []
        loaned_out = []
        for p in players:
            if not hasattr(p, "club") or p.current_ability <= 0:
                continue
            if getattr(p, "on_loan", False) and getattr(p, "parent_club", "") == club.name:
                loaned_out.append(p)
            elif p.club == club.name:
                current_squad.append(p)

        current_squad.sort(key=lambda p: p.current_ability, reverse=True)
        loaned_out.sort(key=lambda p: p.current_ability, reverse=True)

        if current_squad:
            content_layout.addWidget(self._section_label("Current Squad"))
            grid = self._build_player_grid(current_squad, game_year, is_loan_section=False)
            content_layout.addWidget(grid)

        if loaned_out:
            content_layout.addSpacing(12)
            content_layout.addWidget(self._section_label("Loaned Out"))
            grid = self._build_player_grid(loaned_out, game_year, is_loan_section=True)
            content_layout.addWidget(grid)

        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)

    def _build_header(self, club: Club) -> QWidget:
        w = QWidget()
        layout = QGridLayout(w)
        layout.setContentsMargins(0, 0, 0, 8)

        name_lbl = QLabel(club.display_name)
        name_font = QFont()
        name_font.setPointSize(16)
        name_font.setBold(True)
        name_lbl.setFont(name_font)
        name_lbl.setStyleSheet("color: #f0f6fc; font-size: 16px;")
        layout.addWidget(name_lbl, 0, 0, 1, 4)

        info_parts = []
        if club.nation:
            info_parts.append(club.nation)
        if club.league:
            info_parts.append(club.league)
        if info_parts:
            info_lbl = QLabel(" · ".join(info_parts))
            info_lbl.setStyleSheet("color: #8b949e; font-size: 12px;")
            layout.addWidget(info_lbl, 1, 0, 1, 4)

        row = 2
        stats = [
            ("Reputation", str(club.reputation)),
            ("Squad", str(club.squad_size)),
            ("Ability", f"{club.club_ability:.1f}"),
            ("Potential", f"{club.club_potential:.1f}"),
            ("Avg CA", f"{club.avg_ca:.1f}"),
            ("Best CA", str(club.best_ca)),
            ("Avg Age", f"{club.avg_age:.1f}"),
        ]
        col = 0
        for label, val in stats:
            lbl = QLabel(f"<span style='color:#8b949e'>{label}:</span> "
                         f"<span style='color:#c9d1d9'>{val}</span>")
            layout.addWidget(lbl, row, col)
            col += 1
            if col >= 4:
                col = 0
                row += 1

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #21262d;")
        layout.addWidget(sep, row + 1, 0, 1, 4)
        return w

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "color: #f0f6fc; font-size: 13px; font-weight: 600; "
            "padding: 4px 0;"
        )
        return lbl

    def _build_player_grid(self, players: list, game_year: int,
                           is_loan_section: bool) -> QWidget:
        w = QWidget()
        grid = QGridLayout(w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(2)

        headers = ["Name", "Pos", "Age", "CA", "PA", "Status"]
        header_font = QFont()
        header_font.setBold(True)
        for col, h in enumerate(headers):
            lbl = QLabel(h)
            lbl.setFont(header_font)
            lbl.setStyleSheet("color: #8b949e; font-size: 11px; padding: 2px 4px;")
            grid.addWidget(lbl, 0, col)

        dim_style = "color: #484f58; font-size: 11px; padding: 2px 4px;"
        normal_style = "color: #c9d1d9; font-size: 11px; padding: 2px 4px;"

        for row, p in enumerate(players, start=1):
            style = dim_style if is_loan_section else normal_style
            name = getattr(p, "display_name", "") or getattr(p, "name", "")
            pos = getattr(p, "best_position", "") or ""
            age = ""
            if hasattr(p, "birth_year") and p.birth_year and p.birth_year > 1900:
                age = str(game_year - p.birth_year)
            ca = str(p.current_ability) if p.current_ability else ""
            pa = str(p.potential_ability) if hasattr(p, "potential_ability") and p.potential_ability else ""

            status = ""
            if is_loan_section:
                loan_club = getattr(p, "club", "")
                if loan_club:
                    status = f"Loaned out to {loan_club}"
            elif getattr(p, "on_loan", False):
                parent = getattr(p, "parent_club", "")
                if parent:
                    status = f"Loaned in from {parent}"

            cells = [name, pos, age, ca, pa, status]
            for col, text in enumerate(cells):
                lbl = QLabel(text)
                lbl.setStyleSheet(style)
                if col in (2, 3, 4):
                    lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    ca_val = float(text) if text else 0
                    if col in (3, 4) and not is_loan_section:
                        c = _ca_color(ca_val)
                        if c:
                            lbl.setStyleSheet(
                                f"color: {c.name()}; font-size: 11px; padding: 2px 4px;"
                            )
                grid.addWidget(lbl, row, col)

        return w


class ClubViewerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(SS_WIDGET)
        self._players: list = []
        self._game_year: int = 2024
        self._visible: set[str] = set(_DEFAULT_VISIBLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        toolbar = QHBoxLayout()
        search_label = QLabel("Search:")
        search_label.setStyleSheet("color: #8b949e; font-size: 12px;")
        toolbar.addWidget(search_label)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter clubs…")
        self._search.setMaximumWidth(260)
        toolbar.addWidget(self._search)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self._model = ClubTableModel(self)
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setStyleSheet(SS_TABLE)
        self._table.setSortingEnabled(True)
        self._table.setMouseTracking(True)
        self._table.viewport().setMouseTracking(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_column_menu)
        self._table.doubleClicked.connect(self._on_double_click)
        self._table.entered.connect(lambda idx: self._model.set_hover_row(idx.row()))
        self._table.viewport().installEventFilter(self)
        layout.addWidget(self._table)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._do_filter)
        self._search.textChanged.connect(lambda: self._search_timer.start())

        self._apply_column_widths()

    def set_clubs(self, clubs: list[Club], players: list, game_year: int = 2024):
        self._players = players
        self._game_year = game_year
        self._model.set_clubs(clubs)
        self._apply_column_widths()

    def _apply_column_widths(self):
        header = self._table.horizontalHeader()
        for vis_idx, real_idx in enumerate(self._model._visible_cols):
            width = ALL_COLUMNS[real_idx][2]
            header.resizeSection(vis_idx, width)

    def _do_filter(self):
        self._model.filter_by_name(self._search.text())

    def _show_column_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #161b22; color: #c9d1d9; border: 1px solid #30363d; }"
            "QMenu::item:selected { background: #1f6feb33; }"
        )
        for key, label, _ in ALL_COLUMNS:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(key in self._visible)
            action.setData(key)

        chosen = menu.exec(self._table.viewport().mapToGlobal(pos))
        if chosen is not None:
            key = chosen.data()
            if key in self._visible:
                if len(self._visible) > 1:
                    self._visible.discard(key)
            else:
                self._visible.add(key)
            self._model.set_visible(self._visible)
            self._apply_column_widths()

    def _on_double_click(self, index: QModelIndex):
        club = self._model.club_at(index.row())
        if club is None:
            return
        dlg = ClubDetailDialog(club, self._players, self._game_year, parent=self)
        dlg.exec()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Leave and obj is self._table.viewport():
            self._model.clear_hover_row()
        return super().eventFilter(obj, event)
