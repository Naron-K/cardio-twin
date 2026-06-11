"""
Signal source — Phase 2 of the streaming dashboard.

Provides a pluggable interface for sensor reading producers so the
WebSocket layer (Phase 3) and real device feeds can share the same
Session.tick() pipeline without touching session logic.

Classes
-------
SignalSource            Minimal ABC: next() -> dict[str, float].
SimulatedCardioSource   Noisy baseline + arrhythmia injection hook.
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

# Drift magnitudes below this are zeroed to avoid tiny residuals
# persisting indefinitely after arrhythmia decay.
_DRIFT_THRESHOLD: float = 0.5  # bpm


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
    configurable baseline.  inject_arrhythmia() adds a transient HR
    elevation that decays exponentially each tick — this is the "shock"
    the Phase 4 adaptation chart will visualise as the loop drives
    feedback_norm back toward baseline.

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
        # Arrhythmia state — reset by inject_arrhythmia(), decays in next().
        self._drift_magnitude: float = 0.0
        self._drift_decay: float = 0.15

    # ── Public API ────────────────────────────────────────────────────

    def next(self) -> dict[str, float]:
        """
        Emit one sensor reading.

        Adds Gaussian noise to the baseline, applies any active arrhythmia
        drift to HR, then clamps all values to physiological bounds.
        """
        readings: dict[str, float] = {}
        for sensor_id, base in self._baseline.items():
            sigma = self._sigma.get(sensor_id, 0.0)
            noisy = base + self._rng.gauss(0.0, sigma) if sigma > 0.0 else base
            lo, hi = _PHYSIO_RANGES.get(sensor_id, (-math.inf, math.inf))
            readings[sensor_id] = max(lo, min(hi, noisy))

        # Apply arrhythmia drift to HR.  The drift is positive (elevated
        # HR), then multiplied by (1 - _drift_decay) each call so it
        # fades exponentially.  Once below threshold it is zeroed to
        # prevent numeric residuals accumulating over hundreds of ticks.
        if self._drift_magnitude > _DRIFT_THRESHOLD:
            lo, hi = _PHYSIO_RANGES["HR"]
            readings["HR"] = max(lo, min(hi, readings["HR"] + self._drift_magnitude))
            self._drift_magnitude *= (1.0 - self._drift_decay)
        else:
            self._drift_magnitude = 0.0

        return readings

    def inject_arrhythmia(
        self,
        magnitude: float = 30.0,
        decay: float = 0.15,
    ) -> None:
        """
        Trigger a transient HR elevation that fades exponentially.

        magnitude : peak HR elevation in bpm (added to the noisy baseline).
        decay     : fraction of remaining drift removed each tick (0–1).
                    0.15 → ~85 % remains per tick; at 100 ms/tick the
                    perturbation falls below 1 bpm after roughly 25 ticks
                    (~2.5 s), giving the adaptation chart a visible arc.

        Calling inject_arrhythmia() again before the previous drift has
        cleared replaces it immediately (the new magnitude takes effect on
        the very next next() call).
        """
        self._drift_magnitude = float(magnitude)
        self._drift_decay = max(0.0, min(1.0, float(decay)))

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
