"""
Capture the current gate behaviour as a deterministic baseline trace.

This is a BASELINE CAPTURE.  Its whole purpose is to be replayed later
against a refactor to prove the refactor did not change any number.
Determinism is the entire product: two runs must produce byte-identical
JSON.

Each scenario drives a body for 40 cycles from a fixed seed, holding a
forcing from cycle 3 on (the `_settle` pattern in
tests/test_gate_controllers.py), and records one entry per cycle:

  * what the gate did   — open_fraction and transmitted
  * what the receiver holds — provenance_state of the destination
    attribute (the INTER_LAMINA seam), the destination attribute's own
    value, and any extra attributes listed in the WATCH table, resolved
    against the destination lamina's declared attributes
  * for the key body    — the controller's match and drift each cycle

The scenario set, the watch list and the seed are all declared here, at
the top of the module, never buried in the logic.  Nothing in this file
knows that the destination attribute is called CO_ref or that the watch
attribute is called DO2 by name-in-code: the first comes from the
organism spec, the second from the WATCH table resolved against the
destination lamina.

Every recorded float is rounded to 12 decimal places so the file is
stable, and any non-finite value appearing in a trace is refused with a
ValueError rather than being written as a confident-looking wrong
number.

Run from backend/:

    python tools/capture_gate_traces.py          # (re)write the fixture
    python tools/capture_gate_traces.py --check  # compare against disk
"""
from __future__ import annotations

import difflib
import json
import math
import sys
from pathlib import Path

# ── runnable as `python tools/capture_gate_traces.py` (backend/ on
#    sys.path) and importable as `tools.capture_gate_traces` (conftest
#    already puts backend/ on sys.path) ─────────────────────────────────
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from organism import DEFAULT_ORGANISM, Organism  # noqa: E402
from signal_source import SimulatedSource         # noqa: E402

#: Where the baseline fixture is written.
FIXTURE_DIR = BACKEND_DIR / "tests" / "fixtures"
FIXTURE_FILE = FIXTURE_DIR / "gate_traces_v1.json"

#: RNG seed and run length, shared by every scenario.
SEED = 11
CYCLES = 40
#: Decimals kept on every recorded float.  12 is far beyond anything the
#: model can meaningfully resolve, so the fixture is stable without
#: pretending the last digit is a measurement.
DECIMALS = 12
SCHEMA_VERSION = 1

#: Extra destination-lamina attributes to record per cycle, keyed by the
#: resolved organism file name.  DO2 is the downstream result of the
#: seam (DO2 = CaO2 * CO_ref * 10), so it is the number that proves a
#: refactor left the coupling arithmetic alone.  Every name is resolved
#: against the destination lamina's declared attributes at capture time;
#: a name the lamina does not declare is an error, not an omission.
WATCH = {
    "organism.xml":      ["DO2"],
    "organism_key.xml":  ["DO2"],
}

#: The scenarios.  First element is the resolved organism file name
#: ("organism.xml" is the default body and is loaded by passing None),
#: second is the scenario name, third is the per-cycle forcing applied
#: from cycle 3 on (None = no forcing at all).
SCENARIOS = (
    ("organism.xml",      "rest",           None),
    ("organism.xml",      "hr90",           {"HR": 90.0}),
    ("organism.xml",      "hr110",          {"HR": 110.0}),
    ("organism.xml",      "hr200",          {"HR": 200.0}),
    ("organism.xml",      "hr35",           {"HR": 35.0}),
    ("organism_key.xml",  "rest",           None),
    ("organism_key.xml",  "hr140",          {"HR": 140.0}),
    ("organism_key.xml",  "hr150_edv55",    {"HR": 150.0, "EDV": 55.0}),
    ("organism_key.xml",  "hr120_edv60",    {"HR": 120.0, "EDV": 60.0}),
)

#: Scenarios a body is driven through, for a "known" message.
_KNOWN_SCENARIOS: dict = {}
for _name, _scen, _ in SCENARIOS:
    _KNOWN_SCENARIOS.setdefault(_name, []).append(_scen)


# ──────────────────────────────────────────────────────────────────────
# Validation — everything a caller can get wrong fails loudly.
# ──────────────────────────────────────────────────────────────────────

def _known_bodies() -> list:
    """Resolved organism file names this capture knows, in order."""
    return list(dict.fromkeys(name for name, _scen, _ in SCENARIOS))


def validate_cycles(cycles: int) -> None:
    """A run must be at least one cycle long."""
    if isinstance(cycles, bool) or not isinstance(cycles, int) or cycles < 1:
        raise ValueError(
            f"cycles must be an integer >= 1, got {cycles!r}. A baseline "
            f"capture with fewer than one cycle records nothing."
        )


def validate_organism_scenario(organism: str, scenario: str) -> None:
    """
    The body must be one this capture knows, and the scenario one that
    body declares — refusing by name rather than silently substituting
    the default body or the resting scenario, either of which would
    write a confident-looking trace under the wrong label.
    """
    name = resolved_organism_name(organism)
    known = _known_bodies()
    if name not in known:
        raise ValueError(
            f"Unknown organism '{organism}' for gate-trace capture. Known "
            f"bodies: {', '.join(known)}."
        )
    if scenario not in _KNOWN_SCENARIOS[name]:
        raise ValueError(
            f"Organism '{name}' has no scenario '{scenario}'. Known "
            f"scenarios: {', '.join(_KNOWN_SCENARIOS[name])}."
        )


def resolved_organism_name(organism: str | None) -> str:
    """The fixture's name for a body argument: None is the default file."""
    if organism is None:
        return DEFAULT_ORGANISM.name
    return Path(organism).name


def _organism_arg(name: str) -> str | None:
    """The constructor argument that loads this resolved file."""
    return None if name == DEFAULT_ORGANISM.name else name


def validate_forcing(org: Organism, forcing: dict | None,
                     scenario: str = "") -> None:
    """
    Every attribute a scenario forces must be a settable SENSOR on the
    lamina the forcing is aimed at (the gate's source lamina).  A name
    the lamina does not declare would be swallowed silently by
    `Organism.tick`, producing a trace that looks driven but is resting
    — exactly the wrong fixture this phase exists to forbid.
    """
    if not forcing:
        return
    gate = org.spec.gates[0]
    source_twin = org.twins[gate.source.lamina]
    sensors = sorted(source_twin.list_attributes("SENSOR"))
    declared = set(source_twin.attributes)
    for attr in forcing:
        if attr not in declared or attr not in sensors:
            context = f"Scenario '{scenario}' " if scenario else "Scenario "
            raise ValueError(
                f"{context}forces '{attr}', which lamina "
                f"'{gate.source.lamina}' does not declare as a settable "
                f"SENSOR. Declared sensors: {sensors}."
            )


def validate_watch(org: Organism, name: str) -> list:
    """
    Resolve the WATCH table against the gate's destination lamina, and
    refuse a watch name that lamina does not declare.
    """
    gate = org.spec.gates[0]
    dst_twin = org.twins[gate.dest.lamina]
    watch_names = [gate.dest.member] + list(WATCH.get(name, ()))
    declared = set(dst_twin.attributes)
    for watch_name in watch_names:
        if watch_name not in declared:
            raise ValueError(
                f"WATCH['{name}'] names '{watch_name}', which lamina "
                f"'{gate.dest.lamina}' (the destination of gate "
                f"'{gate.id}') does not declare. Declared: "
                f"{sorted(declared)}."
            )
    return watch_names


def clean_value(value, label: str, where: str) -> float:
    """
    One recorded trace number: must be finite, and is rounded to 12
    decimals so the written file is stable.  A NaN or inf in a trace is
    never something to preserve — it is a model bug and the capture
    must say so rather than bake the bug into the baseline.
    """
    if value is None or isinstance(value, bool):
        raise ValueError(
            f"Non-numeric {label} at {where}: {value!r}."
        )
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(
            f"Non-finite value in recorded trace: {label}={value} at "
            f"{where}. A baseline may not contain NaN/inf."
        )
    return round(number, DECIMALS)


def clean_value_or_none(value, label: str, where: str):
    """`clean_value`, except a genuine None stays None (recorded as null)."""
    if value is None:
        return None
    return clean_value(value, label, where)


# ──────────────────────────────────────────────────────────────────────
# Capture
# ──────────────────────────────────────────────────────────────────────

def _load_organism(name: str) -> Organism:
    """A seeded, log-silenced body, exactly the tests' `_settle` pattern."""
    org = Organism(_organism_arg(name))
    for twin in org.twins.values():
        twin._log = lambda *a, **k: None
    org.seed({lamina_id: SimulatedSource(twin, seed=SEED).starting_state()
              for lamina_id, twin in org.twins.items()})
    return org


def capture_run(organism, scenario: str, forcing: dict | None = None,
                cycles: int = CYCLES) -> dict:
    """
    Run one scenario from caller-supplied parts and return its trace
    block (not yet JSON).

    `organism` is a file name, path or None for the default body;
    `scenario` is the scenario's label; `forcing` is the dict applied to
    the gate's source lamina from cycle 3 on (None = no forcing).

    Every argument is validated and a wrong one raises ValueError with
    an actionable message — an unknown body, an unknown scenario, a
    forcing that names an attribute the lamina does not declare, a cycle
    count below 1 — as does any non-finite value the run produces.
    """
    validate_cycles(cycles)
    name = resolved_organism_name(organism)
    validate_organism_scenario(name, scenario)
    forcing = dict(forcing) if forcing else None

    org = _load_organism(name)
    gate = org.spec.gates[0]
    validate_forcing(org, forcing, scenario)
    watch_names = validate_watch(org, name)

    dst_twin = org.twins[gate.dest.lamina]
    dst_attr = dst_twin.attributes[gate.dest.member]
    where_prefix = f"scenario '{scenario}' on '{name}'"

    records = []
    for cycle in range(cycles):
        active = forcing if cycle >= 2 else None
        report = org.tick(
            {gate.source.lamina: active} if active else None
        )
        gate_report = report["gates"][gate.id]
        where = f"{where_prefix}, cycle {cycle + 1}"

        record = {
            "cycle": cycle + 1,
            "open_fraction": clean_value(
                gate_report["open_fraction"], "open_fraction", where),
            "transmitted": clean_value_or_none(
                gate_report["transmitted"], "transmitted", where),
            "provenance_state": (dst_attr.provenance or {}).get("state"),
        }
        for watch_name in watch_names:
            record[watch_name] = clean_value_or_none(
                dst_twin.attributes[watch_name].value, watch_name, where)
        if gate.controller == "key":
            state = gate_report["state"]
            record["match"] = clean_value(
                state["match"], "match", where)
            record["drift"] = clean_value(
                state["drift"], "drift", where)
        records.append(record)

    return {
        "organism":    name,
        "scenario":    scenario,
        "forcing":     forcing,
        "controller":  gate.controller,
        "gate":        gate.id,
        "dest":        str(gate.dest),
        "watch":       watch_names,
        "cycles":      records,
    }


def capture_scenario(organism, scenario: str,
                     cycles: int = CYCLES) -> dict:
    """
    Run one scenario from the SCENARIOS table and return its trace block.
    Validates the organism/scenario names before doing anything else.
    """
    name = resolved_organism_name(organism)
    validate_organism_scenario(name, scenario)
    forcing = _forcing_for(name, scenario)
    return capture_run(name, scenario, forcing=forcing, cycles=cycles)


def _forcing_for(name: str, scenario: str) -> dict | None:
    """The SCENARIOS-table forcing for a validated (body, scenario)."""
    for body, scen, forcing in SCENARIOS:
        if body == name and scen == scenario:
            return forcing
    raise ValueError(f"No forcing declared for scenario '{scenario}' "
                     f"on '{name}'.")


def capture(cycles: int = CYCLES) -> list:
    """Every declared scenario, in declaration order."""
    validate_cycles(cycles)
    return [capture_scenario(name, scenario, cycles=cycles)
            for name, scenario, _forcing in SCENARIOS]


def capture_envelope(cycles: int = CYCLES) -> dict:
    """The full fixture document."""
    validate_cycles(cycles)
    return {
        "schema_version":     SCHEMA_VERSION,
        "seed":               SEED,
        "cycles_per_scenario": cycles,
        "scenarios":          capture(cycles),
    }


def capture_json(cycles: int = CYCLES) -> str:
    """The fixture document as the stable, sorted, newline-terminated text."""
    return json.dumps(capture_envelope(cycles),
                      sort_keys=True, indent=2) + "\n"


def write_fixture(cycles: int = CYCLES, path=Path(FIXTURE_FILE)) -> Path:
    """(Re)write the fixture.  Idempotent: a second run rewrites the same
    bytes.  newline="\\n" pins LF on every platform, so the on-disk bytes
    equal the in-memory capture text exactly."""
    text = capture_json(cycles)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, newline="\n")
    return path


def check_fixture(cycles: int = CYCLES, path=Path(FIXTURE_FILE)) -> tuple:
    """
    Regenerate the capture in memory and compare against the file on
    disk.  Returns (ok: bool, detail: str); detail is a unified diff when
    they differ, an explanatory message otherwise.
    """
    expected = capture_json(cycles)
    path = Path(path)
    if not path.exists():
        return False, (
            f"{path} is missing. Run "
            f"`python tools/capture_gate_traces.py` to write it."
        )
    actual = path.read_text()
    if actual == expected:
        return True, f"{path.name} matches the in-memory re-capture."
    diff = "\n".join(difflib.unified_diff(
        actual.splitlines(), expected.splitlines(),
        fromfile=str(path), tofile="<in-memory re-capture>", lineterm=""))
    return False, diff


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

def _cli(argv: list, check_requested: bool) -> int:
    if check_requested:
        ok, detail = check_fixture()
        print(
            f"OK: {FIXTURE_FILE.name} matches the in-memory re-capture."
            if ok else
            f"FAIL: {FIXTURE_FILE.name} differs from the in-memory "
            f"re-capture."
        )
        if not ok:
            print(detail)
        return 0 if ok else 1

    blocks = capture()
    write_fixture()
    total_cycles = sum(len(block["cycles"]) for block in blocks)
    print(
        f"capture_gate_traces: wrote {len(blocks)} scenarios x "
        f"{CYCLES} cycles ({total_cycles} records, seed {SEED}) to "
        f"{FIXTURE_FILE.relative_to(BACKEND_DIR)}"
    )
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    check_requested = "--check" in argv
    rest = [a for a in argv if a != "--check"]
    if rest:
        print(f"usage: {Path(sys.argv[0]).name} [--check]",
              file=sys.stderr)
        return 2
    return _cli(rest, check_requested)


if __name__ == "__main__":
    sys.exit(main())
