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

import math
import random
from abc import ABC, abstractmethod
from datetime import date as _date
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from bundles import is_finite_number, validate_bundle
from universal_twin import parse_replay_field

if TYPE_CHECKING:  # pragma: no cover — import cycle at runtime, types only
    from universal_twin import UniversalTwin

# Jitter for a sensor whose lamina declares no noise_sigma: a fifth of a
# percent of its declared span.  Enough that a trace is visibly live, small
# enough that nobody reads it as a measurement error someone characterised.
_FALLBACK_SIGMA_FRACTION = 0.002

#: Data seconds replayed per wall-clock second.  Read at call time by
#: ReplaySource so a test or the API can change the available set without
#: rebuilding the class.
REPLAY_SPEEDS = (60, 120, 600)


def _validated_coefficient_overrides(
    twin: "UniversalTwin",
    params: dict | None,
    coefficient_ids,
    mapped: dict,
    *,
    mapped_reason: str,
    only_clause: str,
) -> dict[str, float]:
    """
    Check a params mapping against a lamina's coefficients and return it.

    Shared by the replay and scenario feeds so "a coefficient, and finite"
    has one definition.  The two feeds differ only in how they explain a
    mapped sensor; the rest of the rule, and every message around it, is the
    replay's wording unchanged.
    """
    if params is not None and not isinstance(params, dict):
        raise ValueError(
            f"params must be a mapping of coefficient ids to finite "
            f"values, got {type(params).__name__}."
        )

    coefficient_ids = set(coefficient_ids)
    overrides: dict[str, float] = {}
    for attr_id, value in (params or {}).items():
        if not isinstance(attr_id, str) or attr_id not in coefficient_ids:
            if isinstance(attr_id, str) and attr_id in mapped:
                reason = mapped_reason
            else:
                reason = (
                    f"is not a coefficient SENSOR on lamina "
                    f"{twin.lamina_id}"
                )
            raise ValueError(
                f"params names '{attr_id}', which {reason}. {only_clause}"
            )
        if not is_finite_number(value):
            raise ValueError(
                f"params['{attr_id}']={value!r} is not a finite number."
            )
        overrides[attr_id] = float(value)
    return overrides


class SignalSource(ABC):
    """Minimal interface for a sensor reading producer."""

    #: What kind of feed this is, reported on the wire so a consumer can say so
    #: on screen.  A real device feed would set this to something else, and the
    #: distinction is the whole point: nothing downstream should have to guess
    #: whether it is looking at a patient or at generated numbers.
    KIND: str = "unknown"

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

    KIND = "simulated"

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


class ReplayExhausted(Exception):
    """`next()` was called after the last recorded row had been emitted."""


class ReplaySource(SignalSource):
    """
    A feed that replays one recorded day through a lamina.

    The mapping is the lamina's, not this class's: a SENSOR's
    `replay_field` says whether it comes from a row (`sample.<key>`), the
    day (`day.<key>`), the clock (`clock.hour`, `clock.dt_s`), or nowhere.
    A SENSOR with no `replay_field` is a coefficient: the replay leaves it
    where the file or a caller put it.

    Recorded readings are passed through exactly as recorded.  A null in
    the file is a gap, not a zero: that attribute is omitted from the
    tick and named in `last_missing`, so a consumer can tell "the watch
    did not record this minute" from "the watch recorded a heart rate of
    nothing".

    `clock.hour` is local wall-clock time, not elapsed time: it is the
    bundle's local midnight plus the row's elapsed seconds, done in UTC
    and converted back, so a daylight-saving day actually jumps.
    """

    KIND = "replay"

    def __init__(
        self,
        twin: "UniversalTwin",
        bundle: dict,
        params: dict | None = None,
        speed: int = 60,
    ) -> None:
        if speed not in REPLAY_SPEEDS:
            raise ValueError(
                f"speed={speed!r} is not one of {REPLAY_SPEEDS} data seconds "
                f"per wall second."
            )
        if not isinstance(bundle, dict):
            raise ValueError(
                f"A replay needs a day bundle object, got "
                f"{type(bundle).__name__}."
            )

        label = f"bundle '{bundle.get('subject')}/{bundle.get('date')}'"
        validate_bundle(bundle, label=label)

        mapped: dict[str, str] = {}
        coefficients: list[str] = []
        for attr_id in twin.list_attributes("SENSOR"):
            field = twin.attributes[attr_id].replay_field
            if field is None:
                coefficients.append(attr_id)
            else:
                mapped[attr_id] = field

        if not mapped:
            raise ValueError(
                f"lamina {twin.lamina_id} declares no replay_field, so it "
                f"cannot replay a recorded day."
            )

        day = bundle["day"]
        samples = bundle["samples"]
        for attr_id, declared in mapped.items():
            field, labels = parse_replay_field(declared)
            if labels is not None:
                # A membership field reads a text label, not a number: the
                # recording only has to hold the key, with a label or null.
                source, key = field.split(".", 1)
                holders = [day] if source == "day" else samples
                for position, holder in enumerate(holders):
                    if key not in holder:
                        raise ValueError(
                            f"Attribute '{attr_id}' replays '{declared}', but "
                            f"{'the day object' if source == 'day' else f'sample row {position}'} "
                            f"has no '{key}' field."
                        )
                    label = holder[key]
                    if label is not None and not isinstance(label, str):
                        raise ValueError(
                            f"Attribute '{attr_id}' replays '{declared}', but "
                            f"the recording holds {label!r} where a text label "
                            f"or null belongs."
                        )
                continue
            if field.startswith("day."):
                key = field.split(".", 1)[1]
                if key not in day:
                    raise ValueError(
                        f"Attribute '{attr_id}' replays '{field}', but the "
                        f"bundle's day object has no key '{key}'. Available: "
                        f"{sorted(day)}."
                    )
                value = day[key]
                if value is not None and not is_finite_number(value):
                    raise ValueError(
                        f"Attribute '{attr_id}' replays '{field}', but the "
                        f"bundle holds {value!r}, which is not a finite "
                        f"number."
                    )
            elif field.startswith("sample."):
                key = field.split(".", 1)[1]
                for row_index, row in enumerate(samples):
                    if key not in row:
                        raise ValueError(
                            f"Attribute '{attr_id}' replays '{field}', but "
                            f"sample row {row_index} has no '{key}' field."
                        )
                    value = row[key]
                    if value is not None and not is_finite_number(value):
                        raise ValueError(
                            f"Attribute '{attr_id}' replays '{field}', but "
                            f"sample row {row_index} holds {value!r}, which "
                            f"is not a finite number."
                        )
            elif field not in ("clock.hour", "clock.dt_s"):
                raise ValueError(
                    f"Attribute '{attr_id}' declares replay_field '{field}', "
                    f"which a replay cannot resolve."
                )

        overrides = _validated_coefficient_overrides(
            twin,
            params,
            coefficients,
            mapped,
            mapped_reason="comes from the recorded day during a replay",
            only_clause=(
                "Only a SENSOR without a replay_field may be set for a replay."
            ),
        )

        self._twin = twin
        self._bundle = bundle
        self._mapped = mapped
        self._samples = samples
        self._day = day
        self._grid_s = bundle["grid_s"]
        self._subject = bundle["subject"]
        self._date = bundle["date"]
        self._synthetic = bundle["synthetic"]
        self._fitted = params is not None
        self._tz = (
            timezone.utc
            if bundle["timezone"] == "UTC"
            else ZoneInfo(bundle["timezone"])
        )

        local_day = _date.fromisoformat(self._date)
        self._midnight = datetime(
            local_day.year, local_day.month, local_day.day, tzinfo=self._tz
        )

        self._coefficients: dict[str, float] = {}
        for attr_id in coefficients:
            if attr_id in overrides:
                value = overrides[attr_id]
            else:
                attr = twin.attributes[attr_id]
                if attr.baseline is not None:
                    value = float(attr.baseline)
                else:
                    value = (attr.physio_min + attr.physio_max) / 2.0
            if not math.isfinite(value):
                raise ValueError(
                    f"Coefficient '{attr_id}' has no finite starting value "
                    f"({value!r}). Declare a finite baseline or pass one in "
                    f"params."
                )
            self._coefficients[attr_id] = value

        self._speed = speed
        self._index = 0
        self._last_missing: list[str] = []

    # ── Public API ────────────────────────────────────────────────────

    def next(self) -> dict[str, float]:
        """Emit the current row's readings, then advance to the next row."""
        if self.exhausted:
            self._last_missing = []
            raise ReplayExhausted(
                f"Replay of {self._subject} {self._date} has ended after "
                f"{len(self._samples)} rows."
            )

        readings, missing = self._readings_at(self._index)
        self._index += 1
        self._last_missing = missing
        return readings

    def starting_state(self) -> dict[str, float]:
        """The current row's readings, without advancing (for Session.seed)."""
        if self.exhausted:
            raise ReplayExhausted(
                f"Replay of {self._subject} {self._date} has no current row; "
                f"it ended after {len(self._samples)} rows."
            )
        readings, _ = self._readings_at(self._index)
        return readings

    def set_baseline(self, sensor_id: str, value: float) -> None:
        """
        Update a coefficient for later rows.

        A mapped SENSOR is refused rather than ignored: its value is the
        recording, and silently replacing a measurement with a slider
        would make the replay lie about the day it is replaying.  Unknown
        ids are ignored, as in SimulatedSource.
        """
        if not isinstance(sensor_id, str):
            raise ValueError(
                f"sensor id must be a string, got {type(sensor_id).__name__}."
            )
        if sensor_id in self._mapped:
            raise ValueError(
                f"'{sensor_id}' comes from the recorded day during a replay."
            )
        if sensor_id not in self._coefficients:
            return
        if not is_finite_number(value):
            raise ValueError(
                f"baseline for '{sensor_id}' must be a finite number, got "
                f"{value!r}."
            )
        self._coefficients[sensor_id] = float(value)

    def set_speed(self, speed: int) -> None:
        """Change how much data time passes per wall second."""
        if speed not in REPLAY_SPEEDS:
            raise ValueError(
                f"speed={speed!r} is not one of {REPLAY_SPEEDS} data seconds "
                f"per wall second."
            )
        self._speed = speed

    def rewind(self) -> None:
        """Return to the first recorded row."""
        self._index = 0
        self._last_missing = []

    def describe(self) -> str:
        """One line naming the day and the speed it is replayed at."""
        kind = "synthetic" if self._synthetic else "recorded"
        suffix = " · fitted" if self._fitted else ""
        return (
            f"Replay · {self._subject} · {self._date} · {kind} day · "
            f"x{self._speed}{suffix}"
        )

    def status(self) -> dict:
        """Where the replay is, in the same terms a consumer renders."""
        row_index = self._index - 1 if self._index > 0 else 0
        row = self._samples[row_index]
        local = self._local_time_at(row["t"])
        return {
            "kind": self.KIND,
            "detail": self.describe(),
            "subject": self._subject,
            "date": self._date,
            "synthetic": self._synthetic,
            "coefficients": (
                "fitted" if self._fitted else "declared defaults"
            ),
            "data_time": local.isoformat(),
            "position_s": row["t"],
            "duration_s": len(self._samples) * self._grid_s,
            "speed": self._speed,
            "ended": self.exhausted,
        }

    # ── Properties ────────────────────────────────────────────────────

    @property
    def exhausted(self) -> bool:
        """True once every recorded row has been emitted."""
        return self._index >= len(self._samples)

    @property
    def index(self) -> int:
        """How many rows have been emitted so far."""
        return self._index

    @property
    def speed(self) -> int:
        """Data seconds per wall second."""
        return self._speed

    @property
    def last_missing(self) -> list[str]:
        """Mapped sensors that were null on the most recent next() call."""
        return list(self._last_missing)

    # ── Internal ──────────────────────────────────────────────────────

    def _local_time_at(self, t_s: int) -> datetime:
        """
        Local wall-clock time for `t_s` elapsed seconds after local midnight.

        The arithmetic happens in UTC and is converted back, so a DST
        transition moves the clock rather than stretching the day's data.
        """
        utc_instant = self._midnight.astimezone(timezone.utc) + timedelta(
            seconds=t_s
        )
        return utc_instant.astimezone(self._tz)

    def _readings_at(self, index: int) -> tuple[dict[str, float], list[str]]:
        """Build one row's readings; nulls are omitted and named."""
        row = self._samples[index]
        readings: dict[str, float] = {}
        missing: list[str] = []

        for attr_id, declared in self._mapped.items():
            field, labels = parse_replay_field(declared)
            if labels is not None:
                # 1 when this minute's label is one the lamina lists, else 0.
                # No label (no workout, say) is information, not a gap.
                source, key = field.split(".", 1)
                raw = (row if source == "sample" else self._day)[key]
                readings[attr_id] = 1.0 if raw in labels else 0.0
                continue
            if field == "clock.hour":
                local = self._local_time_at(row["t"])
                value = local.hour + local.minute / 60.0
            elif field == "clock.dt_s":
                value = self._grid_s
            elif field.startswith("sample."):
                value = row[field.split(".", 1)[1]]
            elif field.startswith("day."):
                value = self._day[field.split(".", 1)[1]]
            else:  # pragma: no cover — constructor refuses these
                raise ValueError(
                    f"Attribute '{attr_id}' declares replay_field '{field}', "
                    f"which a replay cannot resolve."
                )

            if value is None:
                missing.append(attr_id)
            else:
                readings[attr_id] = value

        readings.update(self._coefficients)
        return readings, missing


class ScenarioSource(SignalSource):
    """
    A feed that holds one described state, with no noise and no clock.

    A scenario is not a recording: there is no minute-by-minute row to replay.
    It is a set of inputs a domain expert (or a preset file) says the person is
    in, held steady until somebody changes it.  Two consequences follow, and
    both are deliberate:

      * an observed SENSOR is omitted rather than invented.  `HR_obs` is a
        measurement the model predicts, and a scenario has no measurement to
        offer; `last_missing` names it so a consumer can tell a scenario from
        a recording.
      * nothing is clamped except an explicit `set_baseline`.  A preset value
        is the state somebody asked for, including a pathological one; quietly
        moving it into range would make the scenario say something it did not.

    Input precedence per sensor is: a `set_baseline` override, the preset's
    value, a coefficient's `params` value, the declared baseline, then the
    midpoint of the declared range.
    """

    KIND = "scenario"

    def __init__(
        self,
        twin: "UniversalTwin",
        preset: dict,
        params: dict | None = None,
    ) -> None:
        self._twin = twin
        self._sensor_ids: list[str] = []
        self._ranges: dict[str, tuple[float, float]] = {}
        self._observed: set[str] = set()
        coefficients: list[str] = []
        self._declared: dict[str, float] = {}

        for attr_id in twin.list_attributes("SENSOR"):
            attr = twin.attributes[attr_id]
            lo, hi = attr.physio_min, attr.physio_max
            self._sensor_ids.append(attr_id)
            self._ranges[attr_id] = (lo, hi)
            if attr.observed:
                self._observed.add(attr_id)
            if attr.replay_field is None:
                coefficients.append(attr_id)
            if attr.baseline is not None:
                self._declared[attr_id] = float(attr.baseline)
            else:
                self._declared[attr_id] = (lo + hi) / 2.0

        overrides = _validated_coefficient_overrides(
            twin,
            params,
            coefficients,
            {},
            mapped_reason="",
            only_clause="Only a SENSOR without a replay_field is a coefficient.",
        )
        self._fitted = params is not None
        for attr_id, value in overrides.items():
            self._declared[attr_id] = value

        self._overrides: dict[str, float] = {}
        self._preset_values: dict[str, float] = {}
        self._name = ""
        self._label = ""
        self._subject: str | None = None
        self._last_missing: list[str] = []

        self.set_preset(preset)

    # ── Public API ────────────────────────────────────────────────────

    def next(self) -> dict[str, float]:
        """Emit one scenario tick, omitting every observed measurement."""
        readings, missing = self._current_state()
        self._last_missing = missing
        return readings

    def starting_state(self) -> dict[str, float]:
        """The scenario's values, for seeding a Session before the first tick."""
        readings, _ = self._current_state()
        return readings

    def set_baseline(self, sensor_id: str, value: float) -> None:
        """
        Override one input for future ticks, clamped to its declared range.

        An observed SENSOR is refused: the scenario has no measurement, so
        overriding one would be inventing the very number the model is meant
        to be compared against.  Unknown ids are ignored, as in SimulatedSource.
        """
        if sensor_id in self._observed:
            raise ValueError(
                f"'{sensor_id}' is a measurement, and a scenario has none."
            )
        if sensor_id not in self._ranges:
            return
        lo, hi = self._ranges[sensor_id]
        self._overrides[sensor_id] = max(lo, min(hi, float(value)))

    def set_preset(self, preset: dict) -> None:
        """
        Move to a new state.

        Overrides for inputs the new preset sets are dropped — a preset change
        means "go to this state", so a stale slider value must not survive it.
        Overrides for inputs it does not mention are kept, because the new
        preset says nothing about them.
        """
        if not isinstance(preset, dict):
            raise ValueError(
                f"A scenario preset must be a mapping, got "
                f"{type(preset).__name__}."
            )
        supplied = preset.get("values")
        if not isinstance(supplied, dict):
            raise ValueError(
                "A scenario preset must carry a 'values' mapping of attribute "
                "ids to numbers."
            )

        label = preset.get("label") or preset.get("name") or "<preset>"
        values: dict[str, float] = {}
        for attr_id, value in supplied.items():
            attr = self._twin.attributes.get(attr_id)
            if attr is None:
                raise ValueError(
                    f"Preset '{label}' names attribute '{attr_id}', which "
                    f"lamina {self._twin.lamina_id} does not declare."
                )
            if attr.source != "SENSOR":
                raise ValueError(
                    f"Preset '{label}' names '{attr_id}', which is "
                    f"{attr.source}, not SENSOR. A scenario can only set an "
                    f"input."
                )
            if attr.observed:
                raise ValueError(
                    f"Preset '{label}' names '{attr_id}', which is an "
                    f"observed measurement. A scenario has no measurement to "
                    f"set."
                )
            if not is_finite_number(value):
                raise ValueError(
                    f"Preset '{label}' gives '{attr_id}'={value!r}, which is "
                    f"not a finite number."
                )
            values[attr_id] = float(value)

        for attr_id in values:
            self._overrides.pop(attr_id, None)

        self._preset_values = values
        self._name = preset.get("name", "")
        self._label = preset.get("label") or self._name
        self._subject = preset.get("subject")

    def describe(self) -> str:
        """One line naming the state this feed is holding."""
        suffix = " · fitted" if self._fitted else ""
        return f"Scenario · {self._label}{suffix}"

    def status(self) -> dict:
        """The scenario, in the same terms ReplaySource reports itself."""
        return {
            "kind": self.KIND,
            "detail": self.describe(),
            "preset": self._name,
            "label": self._label,
            "subject": self._subject,
            "coefficients": (
                "fitted" if self._fitted else "declared defaults"
            ),
        }

    # ── Properties ────────────────────────────────────────────────────

    @property
    def last_missing(self) -> list[str]:
        """Observed sensors omitted from the most recent next() call."""
        return list(self._last_missing)

    # ── Internal ──────────────────────────────────────────────────────

    def _current_state(self) -> tuple[dict[str, float], list[str]]:
        """Build one tick's readings and the observed sensors it omits."""
        readings: dict[str, float] = {}
        missing: list[str] = []

        for attr_id in self._sensor_ids:
            if attr_id in self._observed:
                missing.append(attr_id)
                continue
            if attr_id in self._overrides:
                value = self._overrides[attr_id]
            elif attr_id in self._preset_values:
                value = self._preset_values[attr_id]
            else:
                value = self._declared[attr_id]
            readings[attr_id] = value

        return readings, missing
