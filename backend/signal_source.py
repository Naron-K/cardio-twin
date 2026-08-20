"""
Signal source — Phase 2 of the streaming dashboard.

Provides a pluggable interface for sensor reading producers so the
WebSocket layer (Phase 3) and real device feeds can share the same
Session.tick() pipeline without touching session logic.

Classes
-------
SignalSource        Minimal ABC: next() -> dict[str, float].
SimulatedSource     Noisy feed built from a twin's own declared sensors.

This file used to carry three hand-kept tables — physiological ranges,
resting baselines and per-sensor noise — for the ten attributes of the
circulatory lamina.  That made the resting state of the twin a fact about a
Python file rather than about the patient, and it meant a lamina describing
anything else got a feed of readings addressed to sensors it does not have.

All three now come from the lamina: `physio_min`/`physio_max` were always in
the XML, and `<baseline>`/`<noise_sigma>` joined them.  A lamina that declares
neither still runs — the midpoint of the declared range with a little jitter is
a legal starting state, just not a characterised one, and `describe()` says so.
"""
from __future__ import annotations

import random
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — import cycle at runtime, types only
    from universal_twin import UniversalTwin

# Jitter for a sensor whose lamina declares no noise_sigma: a fifth of a
# percent of its declared span.  Enough that a trace is visibly live, small
# enough that nobody reads it as a measurement error someone characterised.
_FALLBACK_SIGMA_FRACTION = 0.002


class SignalSource(ABC):
    """Minimal interface for a sensor reading producer."""

    @abstractmethod
    def next(self) -> dict[str, float]:
        """Return one tick's sensor readings as {attr_id: value}."""
        ...


class SimulatedSource(SignalSource):
    """
    Synthetic sensor feed for whichever lamina it is handed.

    Emits one reading per SENSOR attribute the twin declares, jittered around
    that attribute's declared baseline and clamped to its declared range.
    Baselines can be updated live through set_baseline() (driven by the
    WebSocket set_sensor control message).

    Parameters
    ----------
    twin        : the lamina to read sensor declarations from.
    baseline    : per-sensor overrides for the declared baselines.
    noise_sigma : per-sensor overrides for the declared noise.
    seed        : RNG seed for reproducible streams (useful in tests).
    """

    def __init__(
        self,
        twin: "UniversalTwin",
        baseline: dict[str, float] | None = None,
        noise_sigma: dict[str, float] | None = None,
        seed: int | None = None,
    ) -> None:
        self._ranges: dict[str, tuple[float, float]] = {}
        self._baseline: dict[str, float] = {}
        self._sigma: dict[str, float] = {}
        self._undeclared: list[str] = []

        for attr_id in twin.list_attributes("SENSOR"):
            attr = twin.attributes[attr_id]
            lo, hi = attr.physio_min, attr.physio_max
            self._ranges[attr_id] = (lo, hi)
            if attr.baseline is None:
                self._undeclared.append(attr_id)
                self._baseline[attr_id] = (lo + hi) / 2
            else:
                self._baseline[attr_id] = attr.baseline
            self._sigma[attr_id] = (
                attr.noise_sigma
                if attr.noise_sigma is not None
                else abs(hi - lo) * _FALLBACK_SIGMA_FRACTION
            )

        # Explicit overrides win over anything the lamina declared.
        for attr_id, value in (baseline or {}).items():
            if attr_id in self._baseline:
                self._baseline[attr_id] = value
        for attr_id, value in (noise_sigma or {}).items():
            if attr_id in self._sigma:
                self._sigma[attr_id] = value

        self._rng = random.Random(seed)

    # ── Public API ────────────────────────────────────────────────────

    def next(self) -> dict[str, float]:
        """
        Emit one sensor reading.

        Adds Gaussian noise to the baseline, then clamps every value to the
        range the lamina declares for that attribute, so the twin's gates
        never see an out-of-bounds reading produced by noise or drift.
        """
        readings: dict[str, float] = {}
        for sensor_id, base in self._baseline.items():
            sigma = self._sigma.get(sensor_id, 0.0)
            noisy = base + self._rng.gauss(0.0, sigma) if sigma > 0.0 else base
            lo, hi = self._ranges[sensor_id]
            readings[sensor_id] = max(lo, min(hi, noisy))

        return readings

    def set_baseline(self, sensor_id: str, value: float) -> None:
        """
        Persistently update the baseline for one sensor.

        Used by the WebSocket set_sensor control message so that future
        next() calls emit the new value instead of reverting to the previous
        baseline.  Values are clamped to the declared range.  Unknown sensor
        ids are silently ignored.
        """
        if sensor_id not in self._baseline:
            return
        lo, hi = self._ranges[sensor_id]
        self._baseline[sensor_id] = max(lo, min(hi, float(value)))

    def starting_state(self) -> dict[str, float]:
        """
        The unjittered baseline, for seeding a Session before the first tick.

        Replaces the module-level constant a caller used to import: the
        resting state belongs to the lamina, so it is read from the lamina.
        """
        return dict(self._baseline)

    def describe(self) -> str:
        """
        One line for the log saying how well characterised this feed is.

        Sensors running on a midpoint are worth naming: the twin will start
        somewhere legal rather than somewhere anyone chose.
        """
        total = len(self._baseline)
        if not self._undeclared:
            return f"{total} sensors, all with a declared baseline"
        return (
            f"{total} sensors, {len(self._undeclared)} without a declared "
            f"baseline (using range midpoint): {', '.join(self._undeclared)}"
        )
