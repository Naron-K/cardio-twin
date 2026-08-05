"""
Signal source — Phase 2 of the streaming dashboard.

Provides a pluggable interface for sensor reading producers so the
WebSocket layer (Phase 3) and real device feeds can share the same
Session.tick() pipeline without touching session logic.

Classes
-------
SignalSource            Minimal ABC: next() -> dict[str, float].
SimulatedCardioSource   Noisy baseline around configurable values.
"""
from __future__ import annotations

import math
import random
from abc import ABC, abstractmethod

# Physiological bounds from circulatory_lamina.xml.
# next() clamps every reading to these ranges so the twin's gates never
# receive out-of-bounds values from noise or drift.
_PHYSIO_RANGES: dict[str, tuple[float, float]] = {
    "SBP": ( 90.0, 180.0),
    "DBP": ( 60.0, 120.0),
    "HR":  ( 40.0, 200.0),
    "EDV": ( 50.0, 250.0),
    "r":   (  0.01,  1.5),
    "eta": (  3.0,   4.0),
    "L":   (  1.0, 100.0),
    "r_m": (1000.0, 10000.0),
    "r_i": ( 100.0,   500.0),
    "r_e": ( 100.0,   500.0),
}

# Healthy resting baseline — matches presets/normal.xml so the stream
# starts in a physiologically consistent state.
# r=0.15 cm gives R ≈ 39 mmHg·min/L (within gate [10, 40]) and
# Q ≈ 2.4 L/min; r=0.50 yields R ≈ 0.26 (gate fail → Q ≈ 360 L/min).
# r_m=5000 chosen so lambda = sqrt(5000/500) ≈ 3.2 mm (normal range).
_DEFAULT_BASELINE: dict[str, float] = {
    "SBP": 120.0,
    "DBP":  80.0,
    "HR":   72.0,
    "EDV": 120.0,
    "r":    0.15,
    "eta":  3.5,
    "L":   50.0,
    "r_m": 5000.0,
    "r_i":  200.0,
    "r_e":  300.0,
}

# Per-sensor Gaussian noise std dev (absolute, same unit as the sensor).
_DEFAULT_SIGMA: dict[str, float] = {
    "SBP": 2.0,
    "DBP": 1.0,
    "HR":  1.0,
    "EDV": 2.0,
    "r":   0.001,
    "eta": 0.05,
    "L":   0.5,
    "r_m": 50.0,
    "r_i":  5.0,
    "r_e":  5.0,
}

class SignalSource(ABC):
    """Minimal interface for a sensor reading producer."""

    @abstractmethod
    def next(self) -> dict[str, float]:
        """Return one tick's sensor readings as {attr_id: value}."""
        ...


class SimulatedCardioSource(SignalSource):
    """
    Synthetic cardiovascular sensor feed.

    Emits realistic readings with small Gaussian noise around a
    configurable baseline.  Sensor baselines can be updated live through
    set_baseline() (driven by the WebSocket set_sensor control message).

    Parameters
    ----------
    baseline    : per-sensor baselines; defaults to healthy resting values.
    noise_sigma : per-sensor noise std dev; pass {k: 0.0 ...} for zero noise.
    seed        : RNG seed for reproducible streams (useful in tests).
    """

    def __init__(
        self,
        baseline: dict[str, float] | None = None,
        noise_sigma: dict[str, float] | None = None,
        seed: int | None = None,
    ) -> None:
        self._baseline: dict[str, float] = dict(baseline or _DEFAULT_BASELINE)
        self._sigma: dict[str, float] = dict(noise_sigma or _DEFAULT_SIGMA)
        self._rng = random.Random(seed)

    # ── Public API ────────────────────────────────────────────────────

    def next(self) -> dict[str, float]:
        """
        Emit one sensor reading.

        Adds Gaussian noise to the baseline, then clamps all values to
        physiological bounds.
        """
        readings: dict[str, float] = {}
        for sensor_id, base in self._baseline.items():
            sigma = self._sigma.get(sensor_id, 0.0)
            noisy = base + self._rng.gauss(0.0, sigma) if sigma > 0.0 else base
            lo, hi = _PHYSIO_RANGES.get(sensor_id, (-math.inf, math.inf))
            readings[sensor_id] = max(lo, min(hi, noisy))

        return readings

    def set_baseline(self, sensor_id: str, value: float) -> None:
        """
        Persistently update the baseline for one sensor.

        Used by the WebSocket set_sensor control message so that future
        next() calls emit the new value instead of reverting to the
        previous baseline.  Values are clamped to physiological bounds.
        Unknown sensor ids are silently ignored.
        """
        if sensor_id not in self._baseline:
            return
        lo, hi = _PHYSIO_RANGES.get(sensor_id, (-math.inf, math.inf))
        self._baseline[sensor_id] = max(lo, min(hi, float(value)))
