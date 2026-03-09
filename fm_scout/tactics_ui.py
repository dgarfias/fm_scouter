"""Tactics Builder tab widget for FM Scout."""

from __future__ import annotations

from collections import Counter
from typing import Any

from PyQt6.QtCore import Qt, QRectF, pyqtSignal, QItemSelectionModel
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QPalette
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QScrollArea, QFrame, QGroupBox, QGridLayout,
    QSplitter, QTabWidget, QSizePolicy, QAbstractItemView, QListView,
)

from fm_scout.offsets import ATTR_OFFSETS
from fm_scout.tactics_engine import (
    SquadAnalysis, role_score, classify_team_tier, get_style_instructions,
)
from fm_scout.tactics_data import (
    FORMATIONS, ROLE_DEFINITIONS, PLAYING_STYLES, FM24_META, POSITION_TO_ROLES,
)

# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------

SS_WIDGET = """
QWidget {
    background-color: #0d1117;
    color: #c9d1d9;
}
QComboBox {
    background-color: #161b22;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
    min-width: 120px;
}
QComboBox:focus { border-color: #1f6feb; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background-color: #161b22;
    color: #c9d1d9;
    border: 1px solid #30363d;
}
QPushButton {
    background-color: #238636;
    color: #ffffff;
    border: 1px solid #2ea043;
    border-radius: 4px;
    padding: 5px 14px;
    font-size: 12px;
    font-weight: 600;
}
QPushButton:hover { background-color: #2ea043; }
QPushButton:pressed { background-color: #238636; }
QPushButton[class="secondaryBtn"] {
    background-color: #21262d;
    color: #c9d1d9;
    border: 1px solid #30363d;
}
QPushButton[class="secondaryBtn"]:hover {
    background-color: #30363d;
    border-color: #8b949e;
}
QLabel { color: #8b949e; font-size: 11px; }
QScrollArea { border: none; }
QTabWidget::pane {
    border: 1px solid #30363d;
    background-color: #0d1117;
}
QTabBar::tab {
    background-color: #161b22;
    color: #8b949e;
    border: 1px solid #30363d;
    padding: 6px 14px;
    font-size: 11px;
}
QTabBar::tab:selected {
    background-color: #0d1117;
    color: #f0f6fc;
    border-bottom-color: #0d1117;
}
QTabBar::tab:hover { color: #c9d1d9; }
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _score_color(score: float) -> QColor:
    if score >= 85:
        return QColor("#22c55e")
    if score >= 70:
        return QColor("#3fb950")
    if score >= 55:
        return QColor("#d29922")
    if score >= 40:
        return QColor("#ea580c")
    return QColor("#f85149")


def _score_color_hex(score: float) -> str:
    if score >= 85:
        return "#22c55e"
    if score >= 70:
        return "#3fb950"
    if score >= 55:
        return "#d29922"
    if score >= 40:
        return "#ea580c"
    return "#f85149"


def _last_name(name: str, max_len: int = 8) -> str:
    if not name:
        return ""
    last = name.strip().split()[-1]
    return last[:max_len] if len(last) > max_len else last


def _clear_layout(layout):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        elif item.layout() is not None:
            _clear_layout(item.layout())


def _section(layout, title: str):
    lbl = QLabel(title)
    lbl.setStyleSheet(
        "color: #58a6ff; font-size: 12px; font-weight: 700; padding: 6px 0 2px 0;"
    )
    layout.addWidget(lbl)


def _ensure_formation_slots():
    """Patch every FORMATIONS entry with a ``slots`` list built from
    positions / default_roles / default_duties so the engine and UI can
    share a single canonical slot description."""
    for fdata in FORMATIONS.values():
        if "slots" in fdata:
            continue
        positions = fdata.get("positions", [])
        roles = fdata.get("default_roles", [])
        duties = fdata.get("default_duties", [])
        fdata["slots"] = [
            {
                "position": positions[i],
                "role": roles[i] if i < len(roles) else "",
                "duty": duties[i] if i < len(duties) else "support",
            }
            for i in range(len(positions))
        ]


_ensure_formation_slots()

# ---------------------------------------------------------------------------
# Pitch geometry
# ---------------------------------------------------------------------------

PITCH_POSITIONS: dict[str, tuple[int, int]] = {
    "GK":  (50, 92),
    "SW":  (50, 84),
    "DC":  (50, 77),
    "DL":  (15, 77),
    "DR":  (85, 77),
    "WBL": (8,  68),
    "WBR": (92, 68),
    "DM":  (50, 62),
    "DMC": (50, 62),
    "DML": (25, 62),
    "DMR": (75, 62),
    "ML":  (10, 48),
    "MC":  (50, 48),
    "MCL": (35, 48),
    "MCR": (65, 48),
    "MR":  (90, 48),
    "AML": (18, 30),
    "AMC": (50, 30),
    "AMR": (82, 30),
    "ST":  (50, 15),
}


def _compute_slot_positions(positions: list[str]) -> list[tuple[float, float]]:
    """Return *(x%, y%)* per slot, offsetting duplicates horizontally."""
    counts = Counter(positions)
    seen: dict[str, int] = {}
    result: list[tuple[float, float]] = []
    for pos in positions:
        bx, by = PITCH_POSITIONS.get(pos, (50, 50))
        total = counts[pos]
        idx = seen.get(pos, 0)
        seen[pos] = idx + 1
        if total > 1:
            spread = min(36, 18 * (total - 1))
            step = spread / (total - 1)
            x = bx - spread / 2 + step * idx
        else:
            x = float(bx)
        result.append((max(5.0, min(95.0, x)), float(by)))
    return result


# ---------------------------------------------------------------------------
# Pitch widget
# ---------------------------------------------------------------------------


class TacticsPitchWidget(QWidget):
    """Custom-painted football pitch showing formation slots."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 500)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._slots: list[dict[str, Any]] = []

    def set_slots(self, slots_data: list[dict[str, Any]]):
        self._slots = slots_data
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        p.fillRect(0, 0, w, h, QColor("#1e4d2b"))

        line_pen = QPen(QColor(255, 255, 255, 180))
        line_pen.setWidthF(1.5)
        p.setPen(line_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        m = 16
        pw, ph = w - 2 * m, h - 2 * m

        p.drawRect(m, m, pw, ph)

        mid_y = m + ph // 2
        p.drawLine(m, mid_y, m + pw, mid_y)

        cr = min(pw, ph) * 0.07
        p.drawEllipse(QRectF(w / 2 - cr, mid_y - cr, cr * 2, cr * 2))

        pa_w = int(pw * 0.52)
        pa_h = int(ph * 0.14)
        pa_x = m + (pw - pa_w) // 2
        p.drawRect(pa_x, m, pa_w, pa_h)
        p.drawRect(pa_x, m + ph - pa_h, pa_w, pa_h)

        ga_w = int(pw * 0.24)
        ga_h = int(ph * 0.05)
        ga_x = m + (pw - ga_w) // 2
        p.drawRect(ga_x, m, ga_w, ga_h)
        p.drawRect(ga_x, m + ph - ga_h, ga_w, ga_h)

        circle_r = 22
        font_role = QFont("sans-serif", 0)
        font_role.setPixelSize(max(9, circle_r - 8))
        font_role.setBold(True)
        font_name = QFont("sans-serif", 0)
        font_name.setPixelSize(max(8, circle_r - 10))

        for slot in self._slots:
            sx = int(slot["x"] / 100.0 * w)
            sy = int(slot["y"] / 100.0 * h)
            score = slot.get("score", 0)
            color = _score_color(score)

            p.setPen(QPen(color, 2.5))
            p.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 60)))
            p.drawEllipse(sx - circle_r, sy - circle_r, circle_r * 2, circle_r * 2)

            p.setFont(font_role)
            p.setPen(QColor("#f0f6fc"))
            p.drawText(
                QRectF(sx - circle_r, sy - circle_r, circle_r * 2, circle_r),
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignBottom,
                slot.get("role_short", ""),
            )

            name = slot.get("player_name", "")
            if name:
                p.setFont(font_name)
                p.setPen(QColor("#c9d1d9"))
                p.drawText(
                    QRectF(sx - circle_r - 6, sy + circle_r + 1, circle_r * 2 + 12, 14),
                    Qt.AlignmentFlag.AlignCenter,
                    name,
                )

        p.end()


# ---------------------------------------------------------------------------
# Main builder widget
# ---------------------------------------------------------------------------


class TacticsBuilderWidget(QWidget):
    """Full Tactics Builder tab: dropdowns, pitch, analysis tabs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(SS_WIDGET)

        self._players: list[Any] = []
        self._club_players: list[Any] = []
        self._hierarchy: dict[str, dict[str, dict[str, list[str]]]] = {}
        self._club_counts: dict[str, int] = {}
        self._game_year: int = 2024
        self._selected_club: str = ""
        self._analysis: SquadAnalysis | None = None
        self._current_eval: dict[str, Any] | None = None
        self._team_tier: str = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ---- toolbar ----
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        self._cb_continent = QComboBox()
        self._configure_combo_popup(self._cb_continent)
        self._cb_continent.addItem("Continent")
        self._cb_continent.currentTextChanged.connect(self._on_continent_changed)
        toolbar.addWidget(self._cb_continent)

        self._cb_nation = QComboBox()
        self._configure_combo_popup(self._cb_nation)
        self._cb_nation.addItem("Nation")
        self._cb_nation.currentTextChanged.connect(self._on_nation_changed)
        toolbar.addWidget(self._cb_nation)

        self._cb_league = QComboBox()
        self._configure_combo_popup(self._cb_league)
        self._cb_league.addItem("League")
        self._cb_league.currentTextChanged.connect(self._on_league_changed)
        toolbar.addWidget(self._cb_league)

        self._cb_club = QComboBox()
        self._configure_combo_popup(self._cb_club)
        self._cb_club.addItem("Club")
        toolbar.addWidget(self._cb_club)

        self._btn_analyze = QPushButton("Analyze Squad")
        self._btn_analyze.clicked.connect(self._on_analyze)
        toolbar.addWidget(self._btn_analyze)

        self._lbl_tier = QLabel("")
        self._lbl_tier.setStyleSheet(
            "color: #8b949e; font-size: 12px; font-weight: 600; padding: 0 8px;"
        )
        toolbar.addWidget(self._lbl_tier)
        toolbar.addStretch()
        root.addLayout(toolbar)

        # ---- main splitter ----
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        # left panel — formation + pitch
        left = QWidget()
        left_ly = QVBoxLayout(left)
        left_ly.setContentsMargins(0, 0, 0, 0)

        fmt_row = QHBoxLayout()
        fmt_lbl = QLabel("Formation:")
        fmt_lbl.setStyleSheet("color: #8b949e; font-size: 12px;")
        fmt_row.addWidget(fmt_lbl)

        self._cb_formation = QComboBox()
        self._configure_combo_popup(self._cb_formation)
        for fid, fdata in FORMATIONS.items():
            self._cb_formation.addItem(fdata.get("name", fid), fid)
        self._cb_formation.currentIndexChanged.connect(self._on_formation_changed)
        fmt_row.addWidget(self._cb_formation)
        fmt_row.addStretch()
        left_ly.addLayout(fmt_row)

        self._pitch = TacticsPitchWidget()
        left_ly.addWidget(self._pitch, 1)

        self._lbl_score = QLabel("")
        self._lbl_score.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_score.setStyleSheet(
            "color: #c9d1d9; font-size: 13px; font-weight: 600; padding: 4px;"
        )
        left_ly.addWidget(self._lbl_score)
        splitter.addWidget(left)

        # right panel — tabs
        self._tabs = QTabWidget()

        self._best_xi_scroll, self._best_xi_layout = self._make_tab("Best XI")
        self._rec_scroll, self._rec_layout = self._make_tab("Recommendations")
        self._league_scroll, self._league_layout = self._make_tab("League Comparison")

        splitter.addWidget(self._tabs)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([520, 900])
        root.addWidget(splitter, 1)

    # -- tab factory -------------------------------------------------------

    def _make_tab(self, title: str):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        ly = QVBoxLayout(content)
        ly.setContentsMargins(8, 8, 8, 8)
        ly.addStretch()
        scroll.setWidget(content)
        self._tabs.addTab(scroll, title)
        return scroll, ly

    @staticmethod
    def _configure_combo_popup(combo: QComboBox):
        lv = QListView(combo)
        lv.setMouseTracking(True)
        combo.setView(lv)

        pal = lv.palette()
        pal.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.Highlight, QColor("#2b6cb0"))
        pal.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.HighlightedText, QColor("#f0f6fc"))
        pal.setColor(QPalette.ColorGroup.Inactive, QPalette.ColorRole.Highlight, QColor("#2b6cb0"))
        pal.setColor(QPalette.ColorGroup.Inactive, QPalette.ColorRole.HighlightedText, QColor("#f0f6fc"))
        pal.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.Base, QColor("#161b22"))
        pal.setColor(QPalette.ColorGroup.Inactive, QPalette.ColorRole.Base, QColor("#161b22"))
        pal.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.Text, QColor("#c9d1d9"))
        pal.setColor(QPalette.ColorGroup.Inactive, QPalette.ColorRole.Text, QColor("#c9d1d9"))
        lv.setPalette(pal)

        def _select_on_hover(idx):
            lv.selectionModel().setCurrentIndex(
                idx, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        lv._hover_cb = _select_on_hover
        lv.entered.connect(lv._hover_cb)

    # -- public API --------------------------------------------------------

    def set_data(self, my_club=None, players: list[Any] | None = None,
                 game_year: int = 2024):
        """Compatibility API used by main window scan flow."""
        self._game_year = game_year
        players_list = players or []
        club_name = ""
        if isinstance(my_club, str):
            club_name = my_club
        elif my_club is not None:
            club_name = (
                getattr(my_club, "name", "")
                or getattr(my_club, "display_name", "")
                or ""
            )
        self.set_players(players_list, club_name)

    def set_players(self, players: list[Any], my_club: str = ""):
        self._players = players
        self._selected_club = ""

        hierarchy: dict[str, dict[str, dict[str, list[str]]]] = {}
        league_rep: dict[str, int] = {}
        club_counts: dict[str, int] = {}

        for p in players:
            if not getattr(p, "club", "") or getattr(p, "current_ability", 0) <= 0:
                continue
            continent = getattr(p, "league_continent", "") or "Unknown"
            nation = getattr(p, "league_nation", "") or "Unknown"
            league = getattr(p, "league", "") or "Unknown"
            club = p.club

            clubs_list = (
                hierarchy
                .setdefault(continent, {})
                .setdefault(nation, {})
                .setdefault(league, [])
            )
            if club not in clubs_list:
                clubs_list.append(club)

            club_counts[club] = club_counts.get(club, 0) + 1

            wrep = getattr(p, "world_reputation", 0) or 0
            if wrep > league_rep.get(league, 0):
                league_rep[league] = wrep

        def _sort_leagues(leagues_dict: dict[str, list[str]]):
            return {
                lg: sorted(clubs)
                for lg, clubs in sorted(
                    leagues_dict.items(),
                    key=lambda lc: league_rep.get(lc[0], 0),
                    reverse=True,
                )
            }

        for continent in hierarchy:
            for nation in hierarchy[continent]:
                hierarchy[continent][nation] = _sort_leagues(
                    hierarchy[continent][nation]
                )

        self._hierarchy = hierarchy
        self._club_counts = club_counts

        self._cb_continent.blockSignals(True)
        self._cb_continent.clear()
        self._cb_continent.addItem("Continent")
        for c in sorted(hierarchy):
            self._cb_continent.addItem(c)
        self._cb_continent.blockSignals(False)

    # -- hierarchy cascade -------------------------------------------------

    def _on_continent_changed(self, text: str):
        self._cb_nation.blockSignals(True)
        self._cb_nation.clear()
        self._cb_nation.addItem("Nation")
        if text in self._hierarchy:
            for n in sorted(self._hierarchy[text]):
                self._cb_nation.addItem(n)
        self._cb_nation.blockSignals(False)
        self._on_nation_changed(self._cb_nation.currentText())

    def _on_nation_changed(self, text: str):
        self._cb_league.blockSignals(True)
        self._cb_league.clear()
        self._cb_league.addItem("League")
        continent = self._cb_continent.currentText()
        leagues_dict = self._hierarchy.get(continent, {}).get(text, {})
        for lg in leagues_dict:
            self._cb_league.addItem(lg)
        self._cb_league.blockSignals(False)
        self._on_league_changed(self._cb_league.currentText())

    def _on_league_changed(self, text: str):
        self._cb_club.blockSignals(True)
        self._cb_club.clear()
        self._cb_club.addItem("Club")
        continent = self._cb_continent.currentText()
        nation = self._cb_nation.currentText()
        clubs = self._hierarchy.get(continent, {}).get(nation, {}).get(text, [])
        for club in clubs:
            count = self._club_counts.get(club, 0)
            self._cb_club.addItem(f"{club} ({count})", club)
        self._cb_club.blockSignals(False)

    # -- actions -----------------------------------------------------------

    def _on_analyze(self):
        club_data = self._cb_club.currentData()
        club_name = club_data if club_data else self._cb_club.currentText()
        if not club_name or club_name == "Club":
            return
        self._selected_club = club_name

        self._club_players = [
            p for p in self._players
            if getattr(p, "club", "") == club_name
            and getattr(p, "current_ability", 0) > 0
        ]
        if not self._club_players:
            return

        self._analysis = SquadAnalysis(self._club_players)
        league = self._cb_league.currentText()
        self._team_tier = classify_team_tier(
            self._club_players, league if league != "League" else None,
        )
        tier_label = self._team_tier.replace("_", " ").title()
        self._lbl_tier.setText(f"Tier: {tier_label}")

        self._on_formation_changed()
        self._update_league_comparison()

    def _on_formation_changed(self):
        if self._analysis is None:
            return
        fid = self._cb_formation.currentData()
        if not fid:
            return
        ev = self._analysis.evaluate_formation(fid)
        if "error" in ev:
            return
        self._current_eval = ev

        self._update_pitch(ev)
        self._update_best_xi(ev)
        self._update_recommendations(self._analysis)

    # -- view updates ------------------------------------------------------

    def _update_pitch(self, ev: dict[str, Any]):
        fid = self._cb_formation.currentData()
        formation = FORMATIONS.get(fid, {})
        coords = _compute_slot_positions(formation.get("positions", []))

        slots_data: list[dict[str, Any]] = []
        for i, sr in enumerate(ev.get("slots", [])):
            x, y = coords[i] if i < len(coords) else (50.0, 50.0)
            role_def = ROLE_DEFINITIONS.get(sr.get("role_id", ""), {})
            role_short = role_def.get("short", sr.get("role_id", "")[:3].upper())
            player = sr.get("player")
            pname = ""
            if player:
                pname = _last_name(
                    getattr(player, "name", "") or getattr(player, "display_name", "")
                )
            slots_data.append({
                "x": x, "y": y,
                "role_short": role_short,
                "player_name": pname,
                "score": sr.get("current_score", 0),
            })
        self._pitch.set_slots(slots_data)

        overall = ev.get("overall_score", 0)
        potential = ev.get("overall_potential", 0)
        clr = _score_color_hex(overall)
        self._lbl_score.setText(
            f"<span style='color:{clr}'>Overall: {overall:.1f}</span>"
            f"  \u00b7  "
            f"<span style='color:#8b949e'>Potential: {potential:.1f}</span>"
        )

    def _update_best_xi(self, ev: dict[str, Any]):
        _clear_layout(self._best_xi_layout)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)

        hdr_style = (
            "color: #8b949e; font-size: 10px; font-weight: 700; "
            "padding: 4px 6px; border-bottom: 1px solid #30363d;"
        )
        for ci, label in enumerate(["POS", "ROLE / DUTY", "SCORE", "PLAYER", "POSITION", "ALT"]):
            h = QLabel(label)
            h.setStyleSheet(hdr_style)
            grid.addWidget(h, 0, ci)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 3)
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(3, 4)
        grid.setColumnStretch(4, 3)
        grid.setColumnStretch(5, 3)

        row_even = (
            "background-color: #161b22; padding: 4px 6px;"
            "border-bottom: 1px solid #1b2028;"
        )
        row_odd = (
            "background-color: #0d1117; padding: 4px 6px;"
            "border-bottom: 1px solid #1b2028;"
        )

        for ri, sr in enumerate(ev.get("slots", []), start=1):
            row_style = row_even if ri % 2 == 0 else row_odd

            pos = sr.get("position", "")
            role_id = sr.get("role_id", "")
            duty = sr.get("duty", "")
            role_def = ROLE_DEFINITIONS.get(role_id, {})
            role_short = role_def.get("short", role_id[:3].upper())
            role_name = role_def.get("name", role_id)
            cur = sr.get("current_score", 0)
            pot = sr.get("potential_score", 0)
            player = sr.get("player")
            score_clr = _score_color_hex(cur)

            pos_lbl = QLabel(pos)
            pos_lbl.setStyleSheet(
                f"{row_style} color: #c9d1d9; font-size: 11px; font-weight: 600;"
            )
            grid.addWidget(pos_lbl, ri, 0)

            role_w = QWidget()
            role_w.setStyleSheet(row_style)
            role_ly = QVBoxLayout(role_w)
            role_ly.setContentsMargins(4, 2, 4, 2)
            role_ly.setSpacing(0)
            role_name_lbl = QLabel(role_short)
            role_name_lbl.setStyleSheet(
                f"color: #f0f6fc; font-size: 11px; font-weight: 700;"
                f"background-color: {score_clr}; border-radius: 2px;"
                f"padding: 1px 4px;"
            )
            role_ly.addWidget(role_name_lbl)
            duty_lbl = QLabel(duty.title())
            duty_lbl.setStyleSheet("color: #8b949e; font-size: 9px;")
            role_ly.addWidget(duty_lbl)
            grid.addWidget(role_w, ri, 1)

            score_lbl = QLabel(
                f"<span style='color:{score_clr}; font-weight:600;'>{cur:.0f}</span>"
                f"<span style='color:#484f58;'> / {pot:.0f}</span>"
            )
            score_lbl.setStyleSheet(f"{row_style} font-size: 11px;")
            grid.addWidget(score_lbl, ri, 2)

            if player:
                pname = (
                    getattr(player, "display_name", "")
                    or getattr(player, "name", "")
                )
                name_lbl = QLabel(pname)
                name_lbl.setStyleSheet(
                    f"{row_style} color: #c9d1d9; font-size: 11px;"
                )
                if getattr(player, "on_loan", False):
                    name_lbl.setText(f"{pname}  [L]")
                grid.addWidget(name_lbl, ri, 3)

                positions = getattr(player, "positions", {}) or {}
                fit_parts = sorted(
                    [p for p, v in positions.items() if v >= 15],
                    key=lambda p: positions.get(p, 0),
                    reverse=True,
                )
                fit_lbl = QLabel(", ".join(fit_parts) if fit_parts else "-")
                fit_lbl.setStyleSheet(
                    f"{row_style} color: #8b949e; font-size: 11px;"
                )
                grid.addWidget(fit_lbl, ri, 4)

                alt_text = ""
                if self._analysis:
                    alts = self._analysis.best_players_for_role(
                        role_id, duty, top_n=4,
                    )
                    alt_names = [
                        f"{_last_name(getattr(ap, 'display_name', '') or getattr(ap, 'name', ''))} ({asc:.0f})"
                        for ap, asc in alts
                        if ap is not player
                    ]
                    alt_text = ", ".join(alt_names[:2])
                alt_lbl = QLabel(alt_text or "-")
                alt_lbl.setStyleSheet(
                    f"{row_style} color: #484f58; font-size: 10px;"
                )
                grid.addWidget(alt_lbl, ri, 5)
            else:
                empty = QLabel("No suitable player")
                empty.setStyleSheet(f"{row_style} color: #f85149; font-size: 11px;")
                grid.addWidget(empty, ri, 3, 1, 3)

        container = QWidget()
        container.setLayout(grid)
        self._best_xi_layout.addWidget(container)
        self._best_xi_layout.addStretch()

    def _update_recommendations(self, analysis: SquadAnalysis):
        _clear_layout(self._rec_layout)

        fid = self._cb_formation.currentData()

        # -- top formations --
        _section(self._rec_layout, "Top Formations")
        for rank, (f_id, f_ev) in enumerate(
            analysis.recommend_formations(top_n=5), 1
        ):
            f_name = FORMATIONS[f_id].get("name", f_id)
            cur = f_ev.get("overall_score", 0)
            pot = f_ev.get("overall_potential", 0)
            lbl = QLabel(
                f"{rank}. {f_name} \u2014 "
                f"<span style='color:{_score_color_hex(cur)}'>{cur:.1f}</span> "
                f"<span style='color:#8b949e'>/ {pot:.1f} pot</span>"
            )
            lbl.setStyleSheet("color: #c9d1d9; font-size: 11px; padding: 1px 0;")
            self._rec_layout.addWidget(lbl)

        # -- recommended style + instructions --
        if fid:
            _section(self._rec_layout, "Recommended Style")
            style_id = analysis.recommend_style(fid)
            style_info = get_style_instructions(style_id)
            style_name = style_info.get(
                "name", style_id.replace("_", " ").title()
            )
            desc = style_info.get("description", "")

            s_lbl = QLabel(f"<b>{style_name}</b>")
            s_lbl.setStyleSheet("color: #58a6ff; font-size: 12px;")
            self._rec_layout.addWidget(s_lbl)

            if desc:
                d_lbl = QLabel(desc)
                d_lbl.setWordWrap(True)
                d_lbl.setStyleSheet(
                    "color: #8b949e; font-size: 11px; padding: 2px 0;"
                )
                self._rec_layout.addWidget(d_lbl)

            _section(self._rec_layout, "Tactical Instructions")

            mentality = style_info.get("mentality", "balanced")
            m_lbl = QLabel(f"Mentality: <b>{mentality.title()}</b>")
            m_lbl.setStyleSheet("color: #c9d1d9; font-size: 11px;")
            self._rec_layout.addWidget(m_lbl)

            phase_labels = [
                ("in_possession", "In Possession"),
                ("in_transition", "In Transition"),
                ("out_of_possession", "Out of Possession"),
            ]
            for phase_key, phase_title in phase_labels:
                phase_data = style_info.get(phase_key, {})
                if not phase_data:
                    continue
                ph = QLabel(f"<b>{phase_title}:</b>")
                ph.setStyleSheet(
                    "color: #c9d1d9; font-size: 11px; padding-top: 4px;"
                )
                self._rec_layout.addWidget(ph)

                for key, value in phase_data.items():
                    display_key = key.replace("_", " ").title()
                    if isinstance(value, bool):
                        display_val = "Yes" if value else "No"
                        clr = "#3fb950" if value else "#f85149"
                    else:
                        display_val = str(value).replace("_", " ").title()
                        clr = "#c9d1d9"
                    instr = QLabel(
                        f"  {display_key}: "
                        f"<span style='color:{clr}'>{display_val}</span>"
                    )
                    instr.setStyleSheet("color: #8b949e; font-size: 11px;")
                    self._rec_layout.addWidget(instr)

        # -- duty balance --
        if self._current_eval:
            _section(self._rec_layout, "Duty Balance")
            bal = self._current_eval.get("duty_balance", {})
            atk = bal.get("attack", 0)
            sup = bal.get("support", 0)
            dfn = bal.get("defend", 0)
            b_lbl = QLabel(
                f"Attack: {atk}  \u00b7  Support: {sup}  \u00b7  Defend: {dfn}"
            )
            b_lbl.setStyleSheet("color: #c9d1d9; font-size: 11px;")
            self._rec_layout.addWidget(b_lbl)

            warnings = []
            if atk > 5:
                warnings.append(
                    "Too many attack duties \u2014 vulnerable at the back"
                )
            if dfn > 5:
                warnings.append(
                    "Too many defend duties \u2014 may lack creativity"
                )
            if sup < 2:
                warnings.append(
                    "Very few support duties \u2014 transitions may suffer"
                )
            if atk == 0:
                warnings.append(
                    "No attack duties \u2014 may struggle to score"
                )
            for w in warnings:
                wl = QLabel(f"\u26a0 {w}")
                wl.setStyleSheet("color: #d29922; font-size: 11px;")
                self._rec_layout.addWidget(wl)

        # -- tier recommendations --
        _section(self._rec_layout, "Tier Recommendations")
        tier_data = FM24_META.get("tier_recommendations", {}).get(
            self._team_tier, {}
        )
        if tier_data:
            tier_fmts = tier_data.get("formations", [])
            tier_styles = tier_data.get("styles", [])
            if tier_fmts:
                names = [
                    FORMATIONS.get(f, {}).get("name", f) for f in tier_fmts
                ]
                tf = QLabel(f"Suggested formations: {', '.join(names)}")
                tf.setStyleSheet("color: #c9d1d9; font-size: 11px;")
                self._rec_layout.addWidget(tf)
            if tier_styles:
                names = [
                    PLAYING_STYLES.get(s, {}).get("name", s)
                    for s in tier_styles
                ]
                ts = QLabel(f"Suggested styles: {', '.join(names)}")
                ts.setStyleSheet("color: #c9d1d9; font-size: 11px;")
                self._rec_layout.addWidget(ts)
        else:
            nt = QLabel("No tier-specific recommendations available.")
            nt.setStyleSheet("color: #484f58; font-size: 11px;")
            self._rec_layout.addWidget(nt)

        # -- FM24 meta tips --
        _section(self._rec_layout, "FM24 Meta Tips")
        for tip in FM24_META.get("engine_tips", []):
            tl = QLabel(f"\u2022 {tip}")
            tl.setWordWrap(True)
            tl.setStyleSheet("color: #8b949e; font-size: 11px; padding: 1px 0;")
            self._rec_layout.addWidget(tl)

        self._rec_layout.addStretch()

    # -- league comparison -------------------------------------------------

    @staticmethod
    def _top25_for_club(players: list[Any]) -> list[Any]:
        """Select top 25 players for a club, ensuring at least 2 GKs."""
        gks = sorted(
            [p for p in players if getattr(p, "best_position", "") == "GK"],
            key=lambda p: getattr(p, "current_ability", 0),
            reverse=True,
        )[:2]
        gk_set = set(id(p) for p in gks)
        outfield = sorted(
            [p for p in players if id(p) not in gk_set],
            key=lambda p: getattr(p, "current_ability", 0),
            reverse=True,
        )[:25 - len(gks)]
        return gks + outfield

    def _update_league_comparison(self):
        _clear_layout(self._league_layout)

        league = self._cb_league.currentText()
        if not league or league == "League":
            msg = QLabel("Select a league and analyze a squad first.")
            msg.setStyleSheet("color: #8b949e; font-size: 12px; padding: 12px;")
            self._league_layout.addWidget(msg)
            self._league_layout.addStretch()
            return

        my_club = self._selected_club
        if not my_club:
            return

        league_players = [
            p for p in self._players
            if getattr(p, "league", "") == league
            and getattr(p, "current_ability", 0) > 0
        ]
        if not league_players:
            return

        all_clubs: dict[str, list[Any]] = {}
        for p in league_players:
            all_clubs.setdefault(getattr(p, "club", ""), []).append(p)

        clubs = {name: pls for name, pls in all_clubs.items() if len(pls) >= 15}
        if my_club in all_clubs and my_club not in clubs:
            clubs[my_club] = all_clubs[my_club]

        all_attrs = list(
            ATTR_OFFSETS.TECHNICAL_FIELDS
            + ATTR_OFFSETS.MENTAL_FIELDS
            + ATTR_OFFSETS.PHYSICAL_FIELDS
            + ATTR_OFFSETS.GOALKEEPER_FIELDS
        )

        club_avgs: dict[str, dict[str, float]] = {}
        for club_name, club_players in clubs.items():
            top25 = self._top25_for_club(club_players)
            avgs: dict[str, float] = {}
            for attr in all_attrs:
                total = sum(getattr(p, attr, 0) or 0 for p in top25)
                avgs[attr] = total / 25.0
            club_avgs[club_name] = avgs

        num_clubs = len(club_avgs)
        if my_club not in club_avgs:
            return

        def _ordinal(n: int) -> str:
            if 11 <= n % 100 <= 13:
                return f"{n}th"
            return f"{n}{['th','st','nd','rd'][min(n % 10, 3)] if n % 10 < 4 else 'th'}"

        _section(self._league_layout, f"League Comparison — {league}")

        header_lbl = QLabel(
            f"Your team: <b>{my_club}</b> vs {num_clubs} clubs in {league}"
        )
        header_lbl.setStyleSheet("color: #c9d1d9; font-size: 11px; padding: 2px 0 6px 0;")
        self._league_layout.addWidget(header_lbl)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)

        hdr_style = (
            "color: #8b949e; font-size: 10px; font-weight: 700; "
            "padding: 4px 6px; border-bottom: 1px solid #30363d;"
        )
        for ci, label in enumerate(["ATTRIBUTE", "YOUR AVG", "RANK", "BEST TEAM", "BEST AVG"]):
            h = QLabel(label)
            h.setStyleSheet(hdr_style)
            grid.addWidget(h, 0, ci)

        grid.setColumnStretch(0, 4)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(2, 2)
        grid.setColumnStretch(3, 4)
        grid.setColumnStretch(4, 2)

        row_even = (
            "background-color: #161b22; padding: 3px 6px;"
            "border-bottom: 1px solid #1b2028;"
        )
        row_odd = (
            "background-color: #0d1117; padding: 3px 6px;"
            "border-bottom: 1px solid #1b2028;"
        )

        sections = [
            ("Technical", ATTR_OFFSETS.TECHNICAL_FIELDS),
            ("Mental", ATTR_OFFSETS.MENTAL_FIELDS),
            ("Physical", ATTR_OFFSETS.PHYSICAL_FIELDS),
            ("Goalkeeping", ATTR_OFFSETS.GOALKEEPER_FIELDS),
        ]

        ri = 0
        for section_name, fields in sections:
            ri += 1
            sec_lbl = QLabel(section_name)
            sec_lbl.setStyleSheet(
                "color: #58a6ff; font-size: 10px; font-weight: 700; "
                "padding: 6px 6px 2px 6px;"
            )
            grid.addWidget(sec_lbl, ri, 0, 1, 5)

            for attr in fields:
                ri += 1
                row_style = row_even if ri % 2 == 0 else row_odd

                ranked = sorted(
                    club_avgs.items(),
                    key=lambda x: x[1].get(attr, 0),
                    reverse=True,
                )
                rank = next(
                    i for i, (cn, _) in enumerate(ranked, 1) if cn == my_club
                )
                best_club, best_avgs = ranked[0]
                my_avg = club_avgs[my_club][attr]
                best_avg = best_avgs[attr]

                if rank <= 3:
                    rank_clr = "#3fb950"
                elif rank <= num_clubs // 2:
                    rank_clr = "#d29922"
                else:
                    rank_clr = "#f85149"

                display = attr.replace("_", " ").title()

                attr_lbl = QLabel(display)
                attr_lbl.setStyleSheet(f"{row_style} color: #c9d1d9; font-size: 11px;")
                grid.addWidget(attr_lbl, ri, 0)

                avg_lbl = QLabel(f"{my_avg:.1f}")
                avg_lbl.setStyleSheet(f"{row_style} color: #f0f6fc; font-size: 11px; font-weight: 600;")
                grid.addWidget(avg_lbl, ri, 1)

                rank_lbl = QLabel(f"{_ordinal(rank)} of {num_clubs}")
                rank_lbl.setStyleSheet(f"{row_style} color: {rank_clr}; font-size: 11px; font-weight: 600;")
                grid.addWidget(rank_lbl, ri, 2)

                best_lbl = QLabel(best_club)
                best_lbl.setStyleSheet(f"{row_style} color: #8b949e; font-size: 11px;")
                grid.addWidget(best_lbl, ri, 3)

                best_avg_lbl = QLabel(f"{best_avg:.1f}")
                best_avg_lbl.setStyleSheet(f"{row_style} color: #8b949e; font-size: 11px;")
                grid.addWidget(best_avg_lbl, ri, 4)

        container = QWidget()
        container.setLayout(grid)
        self._league_layout.addWidget(container)
        self._league_layout.addStretch()
