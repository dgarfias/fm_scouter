"""Tactics recommendation engine for FM Scout."""

from __future__ import annotations

from statistics import mean
from typing import Any

from fm_scout.tactics_data import (
    ROLE_DEFINITIONS,
    FORMATIONS,
    PLAYING_STYLES,
    FM24_META,
    POSITION_TO_ROLES,
)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_ATTACK_ATTRS = ("finishing", "off_the_ball", "dribbling", "pace", "acceleration")
_DEFEND_ATTRS = ("marking", "tackling", "positioning", "heading", "concentration")

_LEFT_POSITIONS = {"DL", "WBL", "ML", "AML"}
_RIGHT_POSITIONS = {"DR", "WBR", "MR", "AMR"}
_NATURAL_WING_ROLES = {
    "fullback", "wing_back", "complete_wing_back", "winger", "wide_midfielder",
}
_INVERTED_WING_ROLES = {
    "inverted_wing_back", "inside_forward", "inverted_winger", "raumdeuter",
}
_MIDFIELD_POSITIONS = {
    "DM", "DMC", "DML", "DMR", "MC", "MCL", "MCR",
    "ML", "MR", "AML", "AMC", "AMR",
}
_PLAYMAKER_ROLES = {"deep_lying_playmaker", "advanced_playmaker", "regista"}

# ---------------------------------------------------------------------------
# STYLE_INSTRUCTIONS — preset tactical blueprints
# ---------------------------------------------------------------------------

STYLE_INSTRUCTIONS: dict[str, dict[str, Any]] = {
    "gegenpress": {
        "mentality": "positive",
        "in_possession": {
            "passing": "shorter",
            "tempo": "higher",
            "width": "fairly_wide",
        },
        "in_transition": {
            "counter_press": True,
            "counter": True,
        },
        "out_of_possession": {
            "pressing": "much_more_urgent",
            "line_of_engagement": "much_higher",
            "defensive_line": "much_higher",
        },
    },
    "tiki_taka": {
        "mentality": "positive",
        "in_possession": {
            "passing": "shorter",
            "tempo": "higher",
            "width": "fairly_narrow",
            "play_out_of_defence": True,
            "work_ball_into_box": True,
        },
        "in_transition": {
            "counter_press": True,
            "counter": False,
        },
        "out_of_possession": {
            "pressing": "more_urgent",
            "line_of_engagement": "much_higher",
            "defensive_line": "much_higher",
        },
    },
    "vertical_tiki_taka": {
        "mentality": "positive",
        "in_possession": {
            "passing": "shorter",
            "tempo": "higher",
            "width": "fairly_narrow",
            "play_out_of_defence": True,
            "be_more_expressive": True,
        },
        "in_transition": {
            "counter_press": True,
            "counter": False,
        },
        "out_of_possession": {
            "pressing": "more_urgent",
            "line_of_engagement": "higher",
            "defensive_line": "higher",
        },
    },
    "wing_play": {
        "mentality": "positive",
        "in_possession": {
            "passing": "mixed",
            "tempo": "higher",
            "width": "wide",
            "cross_early": True,
        },
        "in_transition": {
            "counter_press": False,
            "counter": True,
        },
        "out_of_possession": {
            "pressing": "standard",
            "line_of_engagement": "standard",
            "defensive_line": "standard",
        },
    },
    "route_one": {
        "mentality": "balanced",
        "in_possession": {
            "passing": "more_direct",
            "tempo": "higher",
            "width": "standard",
        },
        "in_transition": {
            "counter_press": False,
            "counter": True,
        },
        "out_of_possession": {
            "pressing": "standard",
            "line_of_engagement": "standard",
            "defensive_line": "standard",
        },
    },
    "catenaccio": {
        "mentality": "defensive",
        "in_possession": {
            "passing": "shorter",
            "tempo": "lower",
            "width": "fairly_narrow",
        },
        "in_transition": {
            "counter_press": False,
            "counter": True,
        },
        "out_of_possession": {
            "pressing": "less_urgent",
            "line_of_engagement": "deeper",
            "defensive_line": "deeper",
        },
    },
    "control_possession": {
        "mentality": "positive",
        "in_possession": {
            "passing": "shorter",
            "tempo": "lower",
            "width": "fairly_wide",
            "play_out_of_defence": True,
        },
        "in_transition": {
            "counter_press": True,
            "counter": False,
        },
        "out_of_possession": {
            "pressing": "more_urgent",
            "line_of_engagement": "higher",
            "defensive_line": "higher",
        },
    },
    "fluid_counter_attack": {
        "mentality": "cautious",
        "in_possession": {
            "passing": "mixed",
            "tempo": "lower",
            "width": "standard",
        },
        "in_transition": {
            "counter_press": False,
            "counter": True,
        },
        "out_of_possession": {
            "pressing": "standard",
            "line_of_engagement": "deeper",
            "defensive_line": "deeper",
        },
    },
    "direct_counter": {
        "mentality": "cautious",
        "in_possession": {
            "passing": "more_direct",
            "tempo": "higher",
            "width": "standard",
        },
        "in_transition": {
            "counter_press": False,
            "counter": True,
        },
        "out_of_possession": {
            "pressing": "less_urgent",
            "line_of_engagement": "much_deeper",
            "defensive_line": "much_deeper",
        },
    },
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _attr_avg(player: Any, attr_names: tuple[str, ...] | list[str]) -> float:
    """Mean of *player.attributes* values for the given attribute names."""
    vals = [player.attributes.get(a, 0) for a in attr_names]
    return mean(vals) if vals else 0.0


def _pure_attribute_score(player: Any, role_id: str, duty: str | None = None) -> float:
    """Attribute-only suitability score (0-100), ignoring positional fit."""
    role_def = ROLE_DEFINITIONS.get(role_id)
    if role_def is None:
        return 0.0

    key_attrs: list[str] = list(role_def.get("key_attrs", []))
    secondary_attrs: list[str] = list(role_def.get("secondary_attrs", []))

    if duty and "duty_attrs" in role_def:
        extra = role_def["duty_attrs"].get(duty, [])
        if extra:
            key_attrs = key_attrs + list(extra)

    if not key_attrs and not secondary_attrs:
        return 0.0

    key_avg = _attr_avg(player, key_attrs) if key_attrs else 0.0
    sec_avg = _attr_avg(player, secondary_attrs) if secondary_attrs else key_avg

    weighted = key_avg * 0.65 + sec_avg * 0.35
    return max(0.0, min(100.0, (weighted / 20.0) * 100.0))


# ---------------------------------------------------------------------------
# Public scoring API
# ---------------------------------------------------------------------------

def role_score(
    player: Any,
    role_id: str,
    duty: str | None = None,
    slot_position: str | None = None,
) -> float:
    """Score a player's fit for a role+duty in a particular position slot (0-100).

    Combines pure attribute score with positional familiarity, duty
    suitability, and dominant-foot preference.
    """
    base = _pure_attribute_score(player, role_id, duty)

    # --- positional familiarity ---
    role_def = ROLE_DEFINITIONS.get(role_id, {})
    valid_positions: list[str] = role_def.get("positions", [])

    if slot_position:
        best_pos = player.positions.get(slot_position, 0)
    elif valid_positions:
        best_pos = max((player.positions.get(p, 0) for p in valid_positions), default=0)
    else:
        best_pos = 0

    pos_factor = 0.5 + (best_pos / 20.0) * 0.5
    score = base * pos_factor

    if best_pos >= 15:
        score += 5.0
    if best_pos < 10:
        score -= 30.0

    # --- duty boost (up to +5) ---
    if duty:
        atk_avg = _attr_avg(player, _ATTACK_ATTRS)
        def_avg = _attr_avg(player, _DEFEND_ATTRS)
        if duty == "attack" and atk_avg > 13:
            score += min(5.0, (atk_avg - 13) * 0.7)
        elif duty == "defend" and def_avg > 13:
            score += min(5.0, (def_avg - 13) * 0.7)
        elif duty == "support":
            balanced = (atk_avg + def_avg) / 2.0
            if balanced > 12:
                score += min(5.0, (balanced - 12) * 0.5)

    # --- foot preference ---
    if slot_position:
        try:
            left_foot = player.attributes.get("left_foot")
            right_foot = player.attributes.get("right_foot")
            if left_foot is None or right_foot is None:
                raise KeyError("foot data missing")

            is_left = slot_position in _LEFT_POSITIONS
            is_right = slot_position in _RIGHT_POSITIONS

            if is_left or is_right:
                two_footed = left_foot >= 15 and right_foot >= 15
                if two_footed:
                    score += 3.0
                else:
                    is_inverted = role_id in _INVERTED_WING_ROLES
                    want_left = (is_left and not is_inverted) or (is_right and is_inverted)
                    dominant_is_left = left_foot > right_foot
                    if want_left == dominant_is_left:
                        score += 5.0
                    else:
                        score -= 8.0
        except KeyError:
            pass

    return max(0.0, min(100.0, score))


def role_score_pair(
    player: Any,
    role_id: str,
    duty: str | None = None,
    slot_position: str | None = None,
) -> tuple[float, float]:
    """Return *(current_score, potential_score)*.

    Young players (age <= 24) whose PA exceeds CA receive a boosted
    potential score reflecting expected development.
    """
    current = role_score(player, role_id, duty, slot_position)

    ca = getattr(player, "current_ability", 0) or 0
    pa = getattr(player, "potential_ability", 0) or 0
    age = getattr(player, "age", 30)

    if age <= 24 and pa > ca and ca > 0:
        growth = (pa - ca) / ca
        potential = current * (1.0 + growth * 0.5)
        potential = min(100.0, potential)
    else:
        potential = current

    return current, potential


# ---------------------------------------------------------------------------
# Formation synergy
# ---------------------------------------------------------------------------

def _formation_synergy_bonus(slot_results: list[dict[str, Any]]) -> list[float]:
    """Per-slot bonuses/penalties for role-combination synergy."""
    bonuses = [0.0] * len(slot_results)

    indexed = [
        (i, sr.get("role_id", ""), sr.get("duty", ""), sr.get("position", ""))
        for i, sr in enumerate(slot_results)
    ]

    def _by_role(*ids: str) -> list[tuple[int, str, str, str]]:
        return [r for r in indexed if r[1] in ids]

    def _side(pos: str) -> str | None:
        if pos in _LEFT_POSITIONS:
            return "left"
        if pos in _RIGHT_POSITIONS:
            return "right"
        return None

    # --- positive combos ---

    dlp = _by_role("deep_lying_playmaker")
    bwm = _by_role("ball_winning_midfielder")
    if dlp and bwm:
        for s in dlp:
            bonuses[s[0]] += 3.0
        for s in bwm:
            bonuses[s[0]] += 3.0

    mez = _by_role("mezzala")
    if mez and dlp:
        for s in mez:
            bonuses[s[0]] += 2.5
        for s in dlp:
            bonuses[s[0]] += 1.5

    ifs = _by_role("inside_forward", "inverted_winger")
    wbs = _by_role("wing_back", "complete_wing_back")
    for if_s in ifs:
        if_side = _side(if_s[3])
        if if_side is None:
            continue
        for wb_s in wbs:
            if _side(wb_s[3]) == if_side:
                bonuses[if_s[0]] += 3.0
                bonuses[wb_s[0]] += 3.0

    af = _by_role("advanced_forward")
    dlf = _by_role("deep_lying_forward")
    if af and dlf:
        for s in af:
            bonuses[s[0]] += 2.0
        for s in dlf:
            bonuses[s[0]] += 2.0

    # --- negative combos ---

    playmakers = _by_role(*_PLAYMAKER_ROLES)
    if len(playmakers) > 1:
        for s in playmakers:
            bonuses[s[0]] -= 4.0

    mid_slots = [r for r in indexed if r[3] in _MIDFIELD_POSITIONS]
    atk_mids = [r for r in mid_slots if r[2] == "attack"]
    if len(mid_slots) >= 2 and len(atk_mids) == len(mid_slots):
        for s in atk_mids:
            bonuses[s[0]] -= 5.0

    return bonuses


# ---------------------------------------------------------------------------
# SquadAnalysis
# ---------------------------------------------------------------------------

class SquadAnalysis:
    """High-level tactical analysis of a squad."""

    def __init__(self, players: list[Any]):
        self.players = players

    # -- per-role queries --------------------------------------------------

    def best_players_for_role(
        self, role_id: str, duty: str | None = None, top_n: int = 5,
    ) -> list[tuple[Any, float]]:
        scored = [(p, role_score(p, role_id, duty)) for p in self.players]
        scored.sort(key=lambda x: -x[1])
        return scored[:top_n]

    def best_role_for_player(
        self, player: Any, top_n: int = 5,
    ) -> list[tuple[str, str, float]]:
        results: list[tuple[str, str, float]] = []
        for rid, rdef in ROLE_DEFINITIONS.items():
            for duty in rdef.get("duties", ["support"]):
                sc = role_score(player, rid, duty)
                results.append((rid, duty, sc))
        results.sort(key=lambda x: -x[2])
        return results[:top_n]

    # -- formation evaluation ----------------------------------------------

    def evaluate_formation(self, formation_id: str) -> dict[str, Any]:
        """Greedy-assign best-fit players to formation slots.

        Returns a dict with *overall_score*, *overall_potential*, *slots*,
        *weaknesses*, *strengths*, and *duty_balance*.
        """
        formation = FORMATIONS.get(formation_id)
        if not formation:
            return {"error": f"Unknown formation: {formation_id}"}

        slots: list[dict[str, Any]] = formation.get("slots", [])
        available = list(self.players)

        # score every (slot, player) pair
        candidates: list[tuple[float, int, int]] = []
        for si, slot in enumerate(slots):
            for pi, player in enumerate(available):
                sc = role_score(
                    player,
                    slot.get("role", ""),
                    slot.get("duty"),
                    slot.get("position"),
                )
                candidates.append((sc, si, pi))
        candidates.sort(key=lambda x: -x[0])

        assigned_slots: set[int] = set()
        assigned_players: set[int] = set()
        slot_map: dict[int, tuple[Any, float]] = {}

        for sc, si, pi in candidates:
            if si in assigned_slots or pi in assigned_players:
                continue
            slot_map[si] = (available[pi], sc)
            assigned_slots.add(si)
            assigned_players.add(pi)

        slot_results: list[dict[str, Any]] = []
        for si, slot in enumerate(slots):
            pos = slot.get("position", "")
            rid = slot.get("role", "")
            dty = slot.get("duty", "")
            if si in slot_map:
                player, _ = slot_map[si]
                cur, pot = role_score_pair(player, rid, dty, pos)
                slot_results.append({
                    "position": pos,
                    "role_id": rid,
                    "duty": dty,
                    "player": player,
                    "current_score": cur,
                    "potential_score": pot,
                })
            else:
                slot_results.append({
                    "position": pos,
                    "role_id": rid,
                    "duty": dty,
                    "player": None,
                    "current_score": 0.0,
                    "potential_score": 0.0,
                })

        synergy = _formation_synergy_bonus(slot_results)
        for i, bonus in enumerate(synergy):
            slot_results[i]["synergy_bonus"] = bonus
            slot_results[i]["current_score"] = max(
                0.0, min(100.0, slot_results[i]["current_score"] + bonus),
            )

        filled = [sr for sr in slot_results if sr["player"] is not None]
        overall_score = mean(sr["current_score"] for sr in filled) if filled else 0.0
        overall_potential = mean(sr["potential_score"] for sr in filled) if filled else 0.0

        weaknesses = [sr for sr in slot_results if sr["current_score"] < 50]
        strengths = [sr for sr in slot_results if sr["current_score"] >= 75]

        duties = [sr["duty"] for sr in slot_results if sr["player"] is not None]
        duty_balance = {
            "attack": duties.count("attack"),
            "support": duties.count("support"),
            "defend": duties.count("defend"),
        }

        return {
            "overall_score": round(overall_score, 1),
            "overall_potential": round(overall_potential, 1),
            "slots": slot_results,
            "weaknesses": weaknesses,
            "strengths": strengths,
            "duty_balance": duty_balance,
        }

    def recommend_formations(self, top_n: int = 3) -> list[tuple[str, dict[str, Any]]]:
        results = []
        for fid in FORMATIONS:
            ev = self.evaluate_formation(fid)
            if "error" not in ev:
                results.append((fid, ev))
        results.sort(key=lambda x: -x[1].get("overall_score", 0))
        return results[:top_n]

    def squad_gaps(self, formation_id: str) -> list[dict[str, Any]]:
        ev = self.evaluate_formation(formation_id)
        gaps: list[dict[str, Any]] = []
        for sr in ev.get("slots", []):
            if sr["current_score"] < 50:
                gaps.append({
                    "position": sr["position"],
                    "role": sr["role_id"],
                    "duty": sr["duty"],
                    "current_score": sr["current_score"],
                    "severity": "critical" if sr["current_score"] < 30 else "moderate",
                })
        return gaps

    def recommend_style(self, formation_id: str) -> str:
        """Pick the best-fitting playing style for the current squad in a
        given formation based on aggregate squad attributes."""
        ev = self.evaluate_formation(formation_id)
        xi = [sr["player"] for sr in ev.get("slots", []) if sr["player"] is not None]
        if not xi:
            return "control_possession"

        def _squad_avg(attr: str) -> float:
            return mean(p.attributes.get(attr, 10) for p in xi)

        work_rate = _squad_avg("work_rate")
        stamina = _squad_avg("stamina")
        passing = _squad_avg("passing")
        technique = _squad_avg("technique")
        first_touch = _squad_avg("first_touch")
        pace = _squad_avg("pace")
        dribbling = _squad_avg("dribbling")
        tackling = _squad_avg("tackling")
        positioning = _squad_avg("positioning")
        concentration = _squad_avg("concentration")
        off_the_ball = _squad_avg("off_the_ball")
        decisions = _squad_avg("decisions")
        strength = _squad_avg("strength")

        wing_slots = [
            sr for sr in ev.get("slots", [])
            if sr["position"] in (_LEFT_POSITIONS | _RIGHT_POSITIONS)
        ]
        wing_q = mean(sr["current_score"] for sr in wing_slots) if wing_slots else 0.0

        scores: dict[str, float] = {
            "gegenpress": (work_rate + stamina + tackling) / 3.0,
            "tiki_taka": (passing + technique + first_touch) / 3.0,
            "vertical_tiki_taka": (passing + technique + pace + dribbling) / 4.0,
            "wing_play": (wing_q / 5.0 + pace) / 2.0,
            "control_possession": (passing + technique + decisions) / 3.0,
            "route_one": (pace + strength) / 2.0,
            "fluid_counter_attack": (pace + off_the_ball + positioning) / 3.0,
            "direct_counter": (pace + strength + off_the_ball) / 3.0,
            "catenaccio": (tackling + positioning + concentration) / 3.0,
        }
        return max(scores, key=scores.get)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Standalone utilities
# ---------------------------------------------------------------------------

def get_style_instructions(style_id: str) -> dict[str, Any]:
    """Return the tactical instructions for *style_id*, merging the preset
    from ``STYLE_INSTRUCTIONS`` with any extra metadata from
    ``PLAYING_STYLES``."""
    meta = PLAYING_STYLES.get(style_id, {})
    preset = STYLE_INSTRUCTIONS.get(style_id, {})
    return {**meta, **preset}


def classify_team_tier(
    players: list[Any], league: str | None = None,
) -> str:
    """Classify a squad as *elite / top / sub_top / underdog* based on
    average and peak current ability, optionally adjusted by league."""
    if not players:
        return "underdog"

    cas = [getattr(p, "current_ability", 0) or 0 for p in players]
    avg_ca = mean(cas)
    best_ca = max(cas)

    thresholds = FM24_META.get("tier_thresholds", {})
    if league and league in thresholds:
        t = thresholds[league]
    else:
        t = thresholds.get("default", {"elite": 150, "top": 130, "sub_top": 110})

    if avg_ca >= t.get("elite", 150) or best_ca >= 180:
        return "elite"
    if avg_ca >= t.get("top", 130) or best_ca >= 160:
        return "top"
    if avg_ca >= t.get("sub_top", 110) or best_ca >= 140:
        return "sub_top"
    return "underdog"
