"""
The review sheet for a lamina's unreviewed functions and their numbers.

A function may declare ``status="placeholder|draft|reviewed"``.  A function
whose status is placeholder or draft is still a claim waiting for an expert,
and the numbers that claim reads are the ones to replace first.  This tool
prints both lists as a Markdown sheet (or as CSV) straight from the lamina
XML, so the sheet a reviewer works from cannot drift from what the engine
actually runs.

What is listed
--------------

Functions: every function whose status is placeholder or draft, in step
order.  A function with no status is skipped: it makes no claim, so it is not
asking for a reviewer.

Numbers: every SENSOR attribute that declares a <baseline> and is an input of
at least one listed function.  That deliberately leaves out entries and
links, which have no baseline: they are the person's own data, not a number
the model invented.  Rows stay grouped by the XML's segments, in the XML's
order, so "Adaptation (placeholder)" arrives as one block.

Usage, from backend/:

    python tools/list_placeholders.py [--lamina lamina_health]
                                      [--format md|csv] [--out PATH]

Markdown is the default and goes to stdout unless --out names a file.  CSV
without --out prints the numbers table only; with --out it writes two files,
PATH_functions.csv and PATH_numbers.csv (a trailing .csv on PATH is treated
as part of the stem, so ``--out sheet.csv`` writes ``sheet_functions.csv``
and ``sheet_numbers.csv``).

The lamina is loaded with the same loader the engine uses, so a declared
status that the engine would reject fails here too.
"""
from __future__ import annotations

import argparse
import csv
import io
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from laminae import load_twin, resolve_lamina  # noqa: E402
from plan_options import _quiet  # noqa: E402

DEFAULT_LAMINA = "lamina_health"

#: The statuses that mean "an expert still has to replace this".
UNREVIEWED = frozenset({"placeholder", "draft"})
VALID_STATUSES = frozenset({"placeholder", "draft", "reviewed"})

FORMATS = ("md", "csv")

FUNCTION_COLUMNS = ("Function id", "Name", "Status", "Formula", "Source")
NUMBER_COLUMNS = (
    "Segment", "Attribute id", "Name", "Value", "Unit",
    "Allowed range", "Note", "Read by",
)


@dataclass
class Sheet:
    """The two lists a reviewer works from, already in display order."""
    lamina_id: str
    lamina_name: str
    functions: list[dict]
    numbers: list[dict]


# ── Formatting helpers ───────────────────────────────────────────────────────

def _number_text(value: float) -> str:
    """A declared number without a pointless trailing .0."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(
            f"A declared number is not finite ({value!r}); a sheet cannot "
            f"name a number no one can replace."
        )
    if number.is_integer():
        return str(int(number))
    return repr(number)


def _md_cell(value) -> str:
    """
    One Markdown table cell: a pipe or a newline can never break the row.

    The backslash is escaped first so an existing ``\\|`` stays literal text
    instead of becoming a second escape.
    """
    text = "" if value is None else str(value)
    text = text.replace("\\", "\\\\")
    text = text.replace("|", "\\|")
    text = text.replace("\r\n", "<br>").replace("\r", "<br>").replace("\n", "<br>")
    return text


def _md_table(headers, rows) -> list[str]:
    lines = [
        "| " + " | ".join(_md_cell(h) for h in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_md_cell(c) for c in row) + " |")
    return lines


def _step_key(step: str):
    """Sort steps as a person reads them: 1, 1a, 2, 3b, 10."""
    parts = re.findall(r"\d+|\D+", str(step))
    key = []
    for part in parts:
        if part.isdigit():
            key.append((0, int(part), ""))
        else:
            key.append((1, 0, part))
    return tuple(key) if key else ((2, 0, ""),)


# ── Reading the lamina ───────────────────────────────────────────────────────

def _load(path: Path):
    with _quiet():
        return load_twin(path)


def _segments(path: Path, twin) -> list[tuple[str, list[str]]]:
    """
    The XML's segments as (display name, attribute ids), in XML order.

    Segments are read here rather than from the twin because the twin keeps
    the attributes and functions but not the reading order the sheet needs.
    """
    try:
        root = ET.parse(str(path)).getroot()
    except ET.ParseError as exc:
        raise ValueError(
            f"{path} is not valid XML, so no review sheet can be built: {exc}"
        ) from exc

    segments: list[tuple[str, list[str]]] = []
    for segment in root.findall(".//segments/segment"):
        name = (segment.get("name") or segment.get("id") or "").strip()
        if not name:
            raise ValueError(
                f"{path}: a <segment> declares neither a name nor an id, so "
                f"its attributes cannot be placed on the sheet."
            )
        raw = segment.findtext("attributes", "") or ""
        ids = [item.strip() for item in raw.split(",") if item.strip()]
        for attr_id in ids:
            if attr_id not in twin.attributes:
                raise ValueError(
                    f"{path}: segment '{name}' lists attribute '{attr_id}', "
                    f"which the lamina does not declare. Fix the segment or "
                    f"the attribute id before handing this sheet to anyone."
                )
        segments.append((name, ids))
    return segments


def _listed_functions(twin) -> list:
    """Functions that still make an unreviewed claim, in step order."""
    listed = []
    for function in twin.functions.values():
        status = function.status
        if status is None:
            continue  # no status: it makes no claim
        if status not in VALID_STATUSES:
            raise ValueError(
                f"Function '{function.id}' has status '{status}'. Allowed "
                f"values: {', '.join(sorted(VALID_STATUSES))}."
            )
        if status in UNREVIEWED:
            listed.append(function)
    listed.sort(key=lambda function: _step_key(function.step))
    return listed


def _number_rows(twin, functions, segments) -> list[dict]:
    """Every SENSOR with a baseline that a listed function reads, grouped."""
    read_by: dict[str, list[str]] = {}
    for function in functions:
        for input_id in function.inputs:
            read_by.setdefault(input_id, []).append(function.id)

    segment_of: dict[str, str] = {}
    order: list[tuple[str, str]] = []
    for name, ids in segments:
        for attr_id in ids:
            if attr_id in segment_of:
                continue
            segment_of[attr_id] = name
            order.append((name, attr_id))

    for attr_id in twin.attributes:
        if attr_id not in segment_of:
            segment_of[attr_id] = "-"
            order.append(("-", attr_id))

    rows: list[dict] = []
    for segment_name, attr_id in order:
        if attr_id not in read_by:
            continue
        attr = twin.attributes[attr_id]
        if attr.source != "SENSOR":
            continue
        if attr.baseline is None:
            continue
        if not math.isfinite(float(attr.baseline)):
            raise ValueError(
                f"Attribute '{attr_id}' declares a baseline that is not "
                f"finite ({attr.baseline!r}); an expert cannot replace it."
            )
        if float(attr.physio_min) > float(attr.physio_max):
            raise ValueError(
                f"Attribute '{attr_id}' declares range "
                f"{attr.physio_min}..{attr.physio_max}, whose minimum is "
                f"above its maximum. Fix the lamina before listing it."
            )
        rows.append({
            "segment": segment_name,
            "id": attr_id,
            "name": attr.name,
            "value": _number_text(attr.baseline),
            "unit": attr.unit,
            "range": (
                f"{_number_text(attr.physio_min)}.."
                f"{_number_text(attr.physio_max)}"
            ),
            "note": attr.description,
            "read_by": ", ".join(read_by[attr_id]),
        })
    return rows


def build_sheet(lamina_id: str | None = DEFAULT_LAMINA, path=None) -> Sheet:
    """
    Build the review sheet for a lamina.

    ``lamina_id`` is resolved through the engine's own registry, so an
    unknown id raises ``UnknownLamina`` with the available ids.  ``path``
    is for a lamina outside that registry (a test copy, for example); giving
    both is refused rather than silently preferring one.
    """
    if lamina_id is not None and not isinstance(lamina_id, str):
        raise ValueError(
            f"lamina_id must be an id string or None, not "
            f"{type(lamina_id).__name__}. Use --lamina with an id such as "
            f"'{DEFAULT_LAMINA}'."
        )
    if path is not None and lamina_id not in (None, DEFAULT_LAMINA):
        raise ValueError(
            f"Pass either a lamina id or a path, not both ('{lamina_id}' and "
            f"{path})."
        )

    if path is not None:
        resolved = Path(path)
        if not resolved.exists():
            raise ValueError(
                f"Lamina file {resolved} does not exist. Name a readable "
                f"*_lamina.xml or use --lamina with an id from the registry."
            )
        if not resolved.is_file():
            raise ValueError(f"Lamina path {resolved} is not a file.")
    else:
        resolved = resolve_lamina(lamina_id)

    twin = _load(resolved)
    if not twin.functions:
        raise ValueError(
            f"Lamina {resolved} declares no functions, so it is not a model "
            f"a reviewer can sign off. Check the file's <functions> block."
        )

    functions = _listed_functions(twin)
    segments = _segments(resolved, twin)
    numbers = _number_rows(twin, functions, segments)

    return Sheet(
        lamina_id=resolved.stem if path is not None else (lamina_id or DEFAULT_LAMINA),
        lamina_name=getattr(twin, "lamina_name", "") or resolved.stem,
        functions=[
            {
                "id": function.id,
                "name": function.name,
                "status": function.status,
                "formula": function.formula,
                "source": function.source,
            }
            for function in functions
        ],
        numbers=numbers,
    )


# ── Rows, Markdown and CSV ───────────────────────────────────────────────────

def function_rows(sheet: Sheet) -> list[list[str]]:
    """The functions table as row lists, header first (shared by md and csv)."""
    rows = [list(FUNCTION_COLUMNS)]
    for function in sheet.functions:
        rows.append([
            function["id"], function["name"], function["status"],
            function["formula"], function["source"],
        ])
    return rows


def number_rows(sheet: Sheet) -> list[list[str]]:
    """The numbers table as row lists, header first (shared by md and csv)."""
    rows = [list(NUMBER_COLUMNS)]
    for number in sheet.numbers:
        rows.append([
            number["segment"], number["id"], number["name"], number["value"],
            number["unit"], number["range"], number["note"], number["read_by"],
        ])
    return rows


def render_markdown(sheet: Sheet) -> str:
    """The whole sheet: a title, the counts, then the two tables."""
    functions = len(sheet.functions)
    numbers = len(sheet.numbers)
    lines = [
        f"# Placeholder sheet: {sheet.lamina_name}",
        "",
        f"{functions} functions and {numbers} numbers are listed.",
        "",
    ]
    if functions == 0:
        lines.extend([
            "No function declares a status, so this sheet claims nothing to "
            "review.",
            "",
        ])

    lines.append("## Functions not yet reviewed")
    lines.append("")
    lines.extend(_md_table(FUNCTION_COLUMNS, function_rows(sheet)[1:]))
    lines.append("")
    lines.append("## Numbers to replace")
    lines.append("")
    lines.extend(_md_table(NUMBER_COLUMNS, number_rows(sheet)[1:]))
    return "\n".join(lines) + "\n"


def _csv_text(rows: list[list[str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerows(rows)
    return buffer.getvalue()


def _csv_paths(out: Path) -> tuple[Path, Path]:
    base = out.with_suffix("") if out.suffix.lower() == ".csv" else out
    if not base.name:
        raise ValueError(
            f"--out {out} has no file stem, so the two CSV files cannot be "
            f"named. Give a path such as reports/placeholders."
        )
    name = base.name
    parent = base.parent
    return (
        parent / f"{name}_functions.csv",
        parent / f"{name}_numbers.csv",
    )


def _make_parent(path: Path) -> None:
    parent = path.parent
    if parent.exists() and not parent.is_dir():
        raise ValueError(
            f"Cannot write {path}: its parent {parent} exists but is not a "
            f"directory. Name a path under a real directory."
        )
    parent.mkdir(parents=True, exist_ok=True)


def write_csv(sheet: Sheet, out) -> list[Path]:
    """
    Write the two tables beside each other and return both paths.

    The parent directory is created when missing; an ``--out`` that is an
    existing directory is refused because the caller asked for a file stem.
    """
    out_path = Path(out)
    if out_path.exists() and out_path.is_dir():
        raise ValueError(
            f"--out {out_path} is a directory. CSV needs a file stem, for "
            f"example reports/placeholders."
        )
    functions_path, numbers_path = _csv_paths(out_path)
    for target in (functions_path, numbers_path):
        _make_parent(target)

    for target, rows in (
        (functions_path, function_rows(sheet)),
        (numbers_path, number_rows(sheet)),
    ):
        with target.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerows(rows)
    return [functions_path, numbers_path]


def write_markdown(sheet: Sheet, out) -> Path:
    out_path = Path(out)
    if out_path.exists() and out_path.is_dir():
        raise ValueError(
            f"--out {out_path} is a directory. Markdown needs a file path, "
            f"for example reports/placeholders.md."
        )
    _make_parent(out_path)
    out_path.write_text(render_markdown(sheet), encoding="utf-8", newline="\n")
    return out_path


# ── Command line ────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Print the review sheet for every placeholder or draft function "
            "and the numbers it reads."
        )
    )
    parser.add_argument(
        "--lamina", default=DEFAULT_LAMINA,
        help=f"Lamina id to read (default: {DEFAULT_LAMINA}).",
    )
    parser.add_argument(
        "--format", choices=FORMATS, default="md",
        help="md for a Markdown sheet, csv for two comma-separated tables.",
    )
    parser.add_argument(
        "--out",
        help=(
            "Write to this path instead of stdout. CSV takes a stem and "
            "writes PATH_functions.csv and PATH_numbers.csv."
        ),
    )
    args = parser.parse_args(argv)

    sheet = build_sheet(args.lamina)

    if args.format == "md":
        if args.out:
            path = write_markdown(sheet, args.out)
            print(f"Wrote {path}")
        else:
            sys.stdout.write(render_markdown(sheet))
        return 0

    if args.out:
        for path in write_csv(sheet, args.out):
            print(f"Wrote {path}")
    else:
        sys.stdout.write(_csv_text(number_rows(sheet)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
