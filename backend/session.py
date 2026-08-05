"""
Session — Phase 1 of the streaming dashboard.

Holds one live CirculatoryLamina twin + FeedbackController that persist
across many tick() calls.  This is the stateful counterpart to the
stateless /api/feedback/* HTTP endpoints.

Lifecycle
---------
1.  __init__   — build twin, apply initial sensors, run compute_all().
2.  tick()     — update sensors, sync PRELIMINARY, run one feedback
                  cycle, return snapshot + cycle_report.
3.  reset()    — wipe kernel state and zero value_feedback everywhere;
                  equivalent to a fresh session on the same twin config.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from circulatory_lamina import CirculatoryLamina
from feedback_controller import (
    DEFAULT_EPSILON_RATIO,
    DEFAULT_MAX_NORM,
    FeedbackController,
)
from snapshot import _simulation_snapshot, before_after_outcomes
from universal_twin import resolve_polarity

_SCHEMA_PATH = Path(__file__).parent / "circulatory_lamina.xml"


class Session:
    """One long-lived twin + controller driven by repeated tick() calls."""

    def __init__(
        self,
        sensor_data: dict[str, float],
        tag_overrides: dict | None = None,
        epsilon_ratio: float = DEFAULT_EPSILON_RATIO,
        max_norm: float = DEFAULT_MAX_NORM,
    ) -> None:
        self.twin = CirculatoryLamina(str(_SCHEMA_PATH))
        if tag_overrides:
            self._apply_overrides(tag_overrides)
        for attr_id, value in sensor_data.items():
            self.twin.set_sensor(attr_id, value)
        self.twin.compute_all()
        self.controller = FeedbackController(self.twin, epsilon_ratio, max_norm)

    # ── Public API ────────────────────────────────────────────────────

    def tick(self, sensor_update: dict[str, float]) -> dict[str, Any]:
        """
        Run one streaming tick.

        Writes sensor values into X', syncs PRELIMINARY so the outcome
        evaluation in step() sees the new readings (not the previous
        tick's chain), then runs one feedback cycle.

        Returns a simulation snapshot merged with the cycle_report so
        the WebSocket layer has a single JSON blob per tick.
        """
        for attr_id, value in sensor_update.items():
            self.twin.set_sensor(attr_id, value)
        # Sync PRELIMINARY with updated sensors before step() evaluates
        # outcomes; without this, deviations lag one tick behind.
        self.twin.compute_all()
        report = self.controller.step()
        snapshot = _simulation_snapshot(self.twin)
        snapshot["cycle_report"] = report
        # Shadow-pass before/after baseline for the "before vs after tuning"
        # panel.  Runs after step() so "after" reflects this tick's
        # correction; restores twin state before returning.
        snapshot["before_after"] = before_after_outcomes(self.twin)
        return snapshot

    def reset(self) -> None:
        """Zero-fill feedback state and restart the cycle counter."""
        self.controller.reset_kernel_state()

    # ── Internal ──────────────────────────────────────────────────────

    def _apply_overrides(self, overrides: dict) -> None:
        for tag_id, ov in overrides.items():
            tag = self.twin.tags.get(tag_id)
            if tag is None:
                continue
            polarity = ov.get("polarity")
            if polarity is not None:
                tag.polarity = resolve_polarity(polarity)
            params = ov.get("params")
            if params:
                tag.params = {**tag.params, **params}
