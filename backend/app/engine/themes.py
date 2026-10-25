"""The theme list, rounds and theme spins."""
from __future__ import annotations

import json

from .. import logic
from .constants import SEED_IDEAS, SEED_THEMES, EngineError


class ThemesMixin:
    # ------------------------------------------------------------------ themes

    def seed_themes(self) -> None:
        if not self.db.get_setting("themes_seeded"):
            now = self.clock()
            for name, desc, weight in SEED_THEMES:
                self.db.execute("INSERT OR IGNORE INTO themes(name, description, weight, enabled, created_at) "
                                "VALUES (?, ?, ?, 1, ?)", (name, desc, weight, now))
            self.db.set_setting("themes_seeded", True)
        if not self.db.get_setting("theme_ideas_seeded"):  # v0.8.0: starter themes get search ideas, once
            for name, ideas in SEED_IDEAS.items():
                self.db.execute("UPDATE themes SET ideas = ? WHERE name = ? AND ideas = ''", (ideas, name))
            self.db.set_setting("theme_ideas_seeded", True)

    def upgrade_event_configs(self) -> None:
        """v0.7.0 made themes a per-event switch (off for new events). Events from before keep theirs."""
        if self.db.get_setting("themes_switch_added"):
            return
        for ev in self.db.all("SELECT id, config FROM events"):
            cfg = json.loads(ev["config"] or "{}")
            if "themes_enabled" not in cfg:
                cfg["themes_enabled"] = True
                self.db.execute("UPDATE events SET config = ? WHERE id = ?", (json.dumps(cfg), ev["id"]))
        self.db.set_setting("themes_switch_added", True)

    def list_themes(self) -> list[dict]:
        return [self._theme_out(t) for t in self.db.all("SELECT * FROM themes ORDER BY name COLLATE NOCASE")]

    @staticmethod
    def _theme_out(t: dict | None) -> dict | None:
        if not t:
            return None
        return {"id": t["id"], "name": t["name"], "description": t["description"],
                "weight": t["weight"], "enabled": bool(t["enabled"]), "ideas": logic.split_ideas(t.get("ideas"))}

    def save_theme(self, data: dict, theme_id: int | None = None) -> dict:
        name = logic.clean_name(data.get("name", ""))
        if not 1 <= len(name) <= 60:
            raise EngineError("Theme name must be 1 to 60 characters")
        desc = (data.get("description") or "").strip()[:280]
        weight = float(data.get("weight", 1) if data.get("weight") is not None else 1)
        if not 0 <= weight <= 100:
            raise EngineError("Weight must be between 0 and 100")
        enabled = 1 if data.get("enabled", True) else 0
        ideas = ", ".join(logic.split_ideas(data.get("ideas")))[:300]
        clash = self.db.one("SELECT id FROM themes WHERE name = ? COLLATE NOCASE AND id IS NOT ?", (name, theme_id))
        if clash:
            raise EngineError("A theme with that name already exists", 409)
        if theme_id is None:
            theme_id = self.db.insert("INSERT INTO themes(name, description, weight, enabled, ideas, created_at) "
                                      "VALUES (?, ?, ?, ?, ?, ?)", (name, desc, weight, enabled, ideas, self.clock()))
        else:
            if not self._theme(theme_id):
                raise EngineError("Theme not found", 404)
            self.db.execute("UPDATE themes SET name = ?, description = ?, weight = ?, enabled = ?, ideas = ? "
                            "WHERE id = ?", (name, desc, weight, enabled, ideas, theme_id))
        return self._theme_out(self._theme(theme_id))

    def delete_theme(self, theme_id: int) -> None:
        if not self._theme(theme_id):
            raise EngineError("Theme not found", 404)
        self.db.execute("DELETE FROM themes WHERE id = ?", (theme_id,))

    def _pick_theme(self, event_id: int) -> dict | None:
        ev = self.get_event(event_id)
        history = [r["theme_id"] for r in self.db.all(
            "SELECT theme_id FROM rounds WHERE event_id = ? AND theme_id IS NOT NULL ORDER BY id DESC LIMIT 50",
            (event_id,))][::-1]
        themes = self.db.all("SELECT * FROM themes")
        return logic.pick_theme(themes, history, int(ev["config"]["recent_theme_window"]), self.rng)

    # ------------------------------------------------------------------ rounds and themes

    def _start_round(self, event_id: int, number: int) -> dict:
        """A round is one pass through the singer order. With themes on, each round spins a theme."""
        ev = self.get_event(event_id)
        theme = self._pick_theme(event_id) if ev["config"]["themes_enabled"] else None
        round_id = self.db.insert(
            "INSERT INTO rounds(event_id, number, is_superset, theme_id, theme_name, spun_at, started_at) "
            "VALUES (?, ?, 0, ?, ?, ?, ?)",
            (event_id, number, theme["id"] if theme else None, theme["name"] if theme else None,
             self.clock() if theme else None, self.clock()))
        self._set(event_id, current_round=number, current_round_id=round_id)
        self.log(event_id, "playback", f"Round {number} started" + (f": theme {theme['name']}" if theme else ""),
                 automatic=True)
        self.emit(event_id, "round_changed", {"number": number, "theme": self._theme_out(theme)})
        if theme:
            self._emit_spin(event_id, number, theme)
        return self._round(round_id)

    def _theme_candidates(self) -> list[str]:
        return [t["name"] for t in self.db.all("SELECT name FROM themes WHERE enabled = 1 ORDER BY name")]

    def _emit_spin(self, event_id: int, number: int, theme: dict | None, superset: bool = False) -> None:
        ev = self.get_event(event_id)
        self.emit(event_id, "theme_spun", {"round": number, "theme": self._theme_out(theme), "superset": superset,
                                           "duration": int(ev["config"]["spin_seconds"]) + (2 if superset else 0),
                                           "candidates": self._theme_candidates()})

    def force_spin(self, event_id: int) -> None:
        ev = self.get_event(event_id)
        rnd = self._round(ev["current_round_id"])
        if not ev["config"]["themes_enabled"]:
            raise EngineError("Themes are off for this event. Turn them on in Host admin → Events.")
        if not rnd:
            raise EngineError("Start the event first; the first round spins its theme then.")
        theme = self._pick_theme(event_id)
        if not theme:
            raise EngineError("Add or enable at least one theme first")
        self.db.execute("UPDATE rounds SET theme_id = ?, theme_name = ?, spun_at = ? WHERE id = ?",
                        (theme["id"], theme["name"], self.clock(), rnd["id"]))
        self.log(event_id, "event", f"Round {rnd['number']} theme re-spun: {theme['name']}")
        self._emit_spin(event_id, rnd["number"], theme)
