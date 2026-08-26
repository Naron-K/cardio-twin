"""
Session — Phase 1 of the streaming dashboard.

Holds one live twin + FeedbackController that persist
across many tick() calls.  This is the stateful counterpart to the
stateless /api/feedback/* HTTP endpoints.

Lifecycle
---------
1.  __init__   — build twin, apply initial sensors, run compute_all().
2.  tick()     — update sensors, sync PRELIMINARY, run one feedback
                  cycle, return snapshot + cycle_report.
3.  reset()    — wipe kernel state and zero value_feedback everywhere;
                  equivalent to a fresh session on the same twin config.

`OrganismSession` at the bottom is the same idea for a body of several
laminae.  It stands beside `Session` rather than wrapping it: coupling
two laminae should not make running one of them go through machinery it
does not need, so `Session` below is untouched by its existence.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from laminae import load_twin
from feedback_controller import (
    DEFAULT_EPSILON_RATIO,
    DEFAULT_MAX_NORM,
    FeedbackController,
)
from organism import DEFAULT_MAX_TOTAL_NORM, Organism
from signal_source import SimulatedSource
from snapshot import _simulation_snapshot, before_after_outcomes
from universal_twin import resolve_polarity

class Session:
    """One long-lived twin + controller driven by repeated tick() calls."""

    def __init__(
        self,
        sensor_data: dict[str, float] | None = None,
        tag_overrides: dict | None = None,
        epsilon_ratio: float = DEFAULT_EPSILON_RATIO,
        max_norm: float = DEFAULT_MAX_NORM,
        lamina: str | Path | None = None,
    ) -> None:
        # Which lamina, and which class implements it, is laminae.py's call.
        # `lamina` names one per session, so two connections can run two
        # different laminae at once; omitting it takes the process default, so
        # a Session created outside the app (tests, scripts) still picks up the
        # same lamina the API is serving.
        self.twin = load_twin(lamina)
        if tag_overrides:
            self._apply_overrides(tag_overrides)
        self.seed(sensor_data or {})
        self.controller = FeedbackController(self.twin, epsilon_ratio, max_norm)

    def seed(self, sensor_data: dict[str, float]) -> None:
        """
        Write starting sensor values and derive the chain from them.

        Separate from __init__ because the synthetic feed is built *from* the
        twin and so cannot exist before it.  Values addressed to attributes
        this lamina does not declare are skipped rather than raising: a caller
        holding a baseline for another lamina is making a mistake worth
        surviving, and the twin keeps whatever it already had.
        """
        for attr_id, value in sensor_data.items():
            try:
                self.twin.set_sensor(attr_id, value)
            except (KeyError, ValueError):
                continue
        self.twin.compute_all()

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


class OrganismSession:
    """
    One long-lived Organism driven by repeated tick() calls.

    Stands beside `Session` rather than replacing it.  A single-lamina
    session is still the common case, still the thing `/ws/feedback`
    serves by default, and still has no idea this class exists — which is
    the point: coupling two laminae should not make running one of them
    go through machinery it does not need.

    Each lamina gets its OWN synthetic feed, built from its own declared
    sensors, so a body of two laminae starts at rest in both of them.
    """

    def __init__(
        self,
        organism: str | Path | None = None,
        epsilon_ratio: float = DEFAULT_EPSILON_RATIO,
        max_norm: float = DEFAULT_MAX_NORM,
        max_total_norm: float = DEFAULT_MAX_TOTAL_NORM,
        seed: int | None = None,
    ) -> None:
        self.organism = Organism(
            organism,
            epsilon_ratio=epsilon_ratio,
            max_norm=max_norm,
            max_total_norm=max_total_norm,
        )
        self.sources: dict[str, SimulatedSource] = {
            lamina_id: SimulatedSource(twin, seed=seed)
            for lamina_id, twin in self.organism.twins.items()
        }
        self.organism.seed({
            lamina_id: source.starting_state()
            for lamina_id, source in self.sources.items()
        })

    # ── Public API ────────────────────────────────────────────────────

    def sample(self) -> dict[str, dict[str, float]]:
        """One reading per lamina from its own feed."""
        return {lamina_id: source.next()
                for lamina_id, source in self.sources.items()}

    def tick(self, sensor_updates: dict[str, dict[str, float]] | None = None
             ) -> dict[str, Any]:
        """
        Run one organism cycle and return a snapshot of the whole body.

        Shape mirrors Session.tick(): the per-lamina snapshots are exactly
        what a single-lamina session sends, nested under their lamina id,
        with the organism's own report alongside.  Anything that can read
        one lamina can read one of these without learning a second format.
        """
        report = self.organism.tick(sensor_updates or {})
        snapshot = self.organism.snapshot()
        snapshot["organism_report"] = report
        for lamina_id, lamina_snapshot in snapshot["laminae"].items():
            lamina_snapshot["cycle_report"] = report["cycle_reports"][lamina_id]
            lamina_snapshot["before_after"] = before_after_outcomes(
                self.organism.twins[lamina_id]
            )
        return snapshot

    def set_sensor(self, lamina_id: str, attr_id: str, value: float) -> None:
        """
        Command one sensor on one lamina.

        Writes the feed's baseline as well as the twin, so the next
        reading comes back near the commanded value instead of reverting —
        the same two-step Session's WebSocket handler does, for the same
        reason.
        """
        source = self.sources.get(lamina_id)
        if source is not None:
            source.set_baseline(attr_id, value)
        twin = self.organism.twins.get(lamina_id)
        if twin is None:
            return
        try:
            twin.set_sensor(attr_id, value)
        except (KeyError, ValueError):
            pass  # not a sensor on this lamina — the contract refusing is fine

    def reset(self) -> None:
        """Zero every lamina's feedback state, every gate's, and the breaker."""
        self.organism.reset()
