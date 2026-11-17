"""
The sheet handed to the expert who replaces the placeholder models.

The tests pin what the sheet must contain and, just as importantly, what it
must leave out: entries and links are the person's data, not invented numbers.
A description holding a pipe must not break the Markdown table, and the CSV
must survive a round trip through the csv module unchanged.
"""
import csv
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from laminae import LAMINA_DIR, UnknownLamina, load_twin
from tools.list_placeholders import (
    build_sheet,
    function_rows,
    number_rows,
    render_markdown,
    write_csv,
)

HEALTH = LAMINA_DIR / "health_lamina.xml"


def _segment_attributes(path: Path, name: str) -> list[str]:
    root = ET.parse(str(path)).getroot()
    for segment in root.findall(".//segments/segment"):
        if segment.get("name") == name:
            raw = segment.findtext("attributes", "") or ""
            return [item.strip() for item in raw.split(",") if item.strip()]
    raise AssertionError(f"no segment named {name!r} in {path}")


def _cells(line: str) -> list[str]:
    """Split a Markdown row on unescaped pipes only."""
    body = line.strip()
    assert body.startswith("|")
    body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in body:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            current.append(char)
            escaped = True
        elif char == "|":
            cells.append("".join(current))
            current = []
        else:
            current.append(char)
    cells.append("".join(current))
    return [cell.strip() for cell in cells]


def _tables(markdown: str) -> list[list[str]]:
    groups: list[list[str]] = []
    current: list[str] = []
    for line in markdown.splitlines():
        if line.startswith("|"):
            current.append(line)
        elif current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def _copy_with_pipe(tmp_path: Path) -> Path:
    """A health lamina whose first adaptation note holds a pipe and newline."""
    tree = ET.parse(str(HEALTH))
    root = tree.getroot()
    adaptation = _segment_attributes(HEALTH, "Adaptation (placeholder)")
    first_id = adaptation[0]
    for attribute in root.findall(".//attributes/attribute"):
        if attribute.get("id") != first_id:
            continue
        description = attribute.find("description")
        assert description is not None
        description.text = (
            (description.text or "")
            + " A reviewer must say who | which population"
            + "\nand which trial."
        )
    path = tmp_path / "health_lamina.xml"
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return path


def test_numbers_cover_adaptation_and_read_coefficients():
    sheet = build_sheet("lamina_health")
    ids = [number["id"] for number in sheet.numbers]

    assert len(ids) == len(set(ids)), "an attribute was listed twice"

    adaptation = _segment_attributes(HEALTH, "Adaptation (placeholder)")
    assert len(adaptation) == 32
    assert set(adaptation) <= set(ids)

    start = ids.index(adaptation[0])
    assert ids[start:start + len(adaptation)] == adaptation

    twin = load_twin(HEALTH)
    listed = {function["id"] for function in sheet.functions}
    coefficients = _segment_attributes(HEALTH, "Model Coefficients")
    read_coefficients = {
        attr_id
        for attr_id in coefficients
        if any(attr_id in twin.functions[fid].inputs for fid in listed)
    }
    assert read_coefficients, "no coefficient is read by a listed function"
    assert read_coefficients <= set(ids)

    for number in sheet.numbers:
        assert twin.attributes[number["id"]].source == "SENSOR"
        assert twin.attributes[number["id"]].baseline is not None
        assert number["read_by"]


def test_entries_links_and_weeks_are_not_listed():
    sheet = build_sheet("lamina_health")
    ids = {number["id"] for number in sheet.numbers}

    entries = _segment_attributes(HEALTH, "Entered by the person")
    links = _segment_attributes(HEALTH, "From the activity twin")
    assert entries and links

    for attr_id in entries + links + ["weeks"]:
        assert attr_id not in ids


def test_every_listed_function_is_unreviewed():
    sheet = build_sheet("lamina_health")
    assert sheet.functions
    for function in sheet.functions:
        assert function["status"] in {"placeholder", "draft"}


def test_markdown_tables_keep_a_constant_column_count_with_a_pipe(tmp_path):
    path = _copy_with_pipe(tmp_path)
    sheet = build_sheet(path=path)
    markdown = render_markdown(sheet)

    assert "\\|" in markdown, "the injected pipe was not escaped"
    assert "<br>" in markdown, "the injected newline was not escaped"

    tables = _tables(markdown)
    assert len(tables) == 2

    for table in tables:
        counts = {len(_cells(line)) for line in table}
        assert len(counts) == 1, f"ragged table: {counts}"
        widths = counts.pop()
        assert widths == len(function_rows(sheet)[0]) or widths == len(
            number_rows(sheet)[0]
        )


def test_csv_round_trips_through_the_csv_module(tmp_path):
    sheet = build_sheet("lamina_health")
    paths = write_csv(sheet, tmp_path / "sheet")
    assert [path.name for path in paths] == [
        "sheet_functions.csv",
        "sheet_numbers.csv",
    ]

    expected = (function_rows(sheet), number_rows(sheet))
    for path, wanted in zip(paths, expected):
        with path.open(encoding="utf-8", newline="") as handle:
            got = list(csv.reader(handle))
        assert got == wanted


def test_unknown_lamina_is_refused_with_the_available_ids():
    with pytest.raises(UnknownLamina) as caught:
        build_sheet("lamina_not_here")

    message = str(caught.value)
    assert "lamina_not_here" in message
    assert "Available" in message
    assert "lamina_health" in message


def test_a_lamina_with_no_status_says_the_sheet_is_empty():
    sheet = build_sheet("lamina_circulatory")
    assert sheet.functions == []
    assert sheet.numbers == []

    markdown = render_markdown(sheet)
    assert "0 functions and 0 numbers are listed." in markdown
    assert "No function declares a status" in markdown
