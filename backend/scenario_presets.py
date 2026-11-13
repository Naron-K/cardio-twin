"""
Scenario presets — named states a scenario feed can hold.

A scenario preset is the same XML shape the patient presets use, with two
additions that make it a state of a lamina rather than a bag of numbers:
`<metadata><lamina>` names the lamina it belongs to, and the metadata carries
the label, description, optional subject and sort order.  The existing patient
presets have no `<lamina>` element and are therefore never offered as scenario
presets.

Discovery and loading are separate on purpose.  `list_presets` is allowed to
meet a malformed file and skip it: one broken preset must not hide the rest.
`load_preset` is asked for one named state and refuses anything it cannot read
completely, naming the file and the element that failed.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from bundles import is_finite_number

PRESET_DIR = Path(__file__).resolve().parent.parent / "presets"

_NAME_PATTERN = re.compile(r"^[a-z0-9_]{1,32}$")
_DEFAULT_ORDER = 99

logger = logging.getLogger(__name__)


class UnknownPreset(LookupError):
    """A request named a scenario preset that is not on disk."""

    def __init__(self, lamina_id: str, name: str, available: list[str]) -> None:
        self.lamina_id = lamina_id
        self.name = name
        self.available = list(available)
        listing = ", ".join(self.available) if self.available else "(no presets)"
        super().__init__(
            f"No preset '{name}' for lamina '{lamina_id}'. Available: {listing}"
        )


def _metadata_of(path: Path) -> dict:
    """Read the metadata block a scenario preset must carry."""
    try:
        root = ET.parse(str(path)).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"{path}: cannot parse XML: {exc}") from exc

    metadata = root.find("metadata")
    if metadata is None:
        raise ValueError(f"{path}: missing <metadata>.")

    order_text = (metadata.findtext("order") or "").strip()
    if order_text:
        try:
            order = int(order_text)
        except ValueError as exc:
            raise ValueError(
                f"{path}: <order> {order_text!r} is not an integer."
            ) from exc
    else:
        order = _DEFAULT_ORDER

    label = (metadata.findtext("name") or "").strip()
    return {
        "lamina": (metadata.findtext("lamina") or "").strip(),
        "label": label or path.stem,
        "description": (metadata.findtext("description") or "").strip(),
        "subject": (metadata.findtext("subject") or "").strip() or None,
        "order": order,
    }


def list_presets(
    lamina_id: str, preset_dir: Path = PRESET_DIR
) -> list[dict]:
    """
    Every scenario preset for `lamina_id`, sorted by order then name.

    A file with no `<metadata><lamina>`, or one naming another lamina, is not
    a preset for this lamina and is simply not listed.  A file that cannot be
    read at all is logged and skipped rather than taking the listing down.
    """
    base = Path(preset_dir)
    if not base.is_dir():
        return []

    found: list[dict] = []
    for path in sorted(base.glob("**/*.xml")):
        if not path.is_file():
            continue
        try:
            metadata = _metadata_of(path)
        except (OSError, ValueError) as exc:
            logger.warning("Skipping malformed scenario preset: %s", exc)
            continue
        if metadata["lamina"] != lamina_id:
            continue
        found.append({
            "name": path.stem,
            "label": metadata["label"],
            "description": metadata["description"],
            "subject": metadata["subject"],
            "order": metadata["order"],
        })

    found.sort(key=lambda preset: (preset["order"], preset["name"]))
    return found


def _read_values(path: Path) -> dict[str, float]:
    """Read `<sensor_data>` as attribute id to finite float."""
    try:
        root = ET.parse(str(path)).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"{path}: cannot parse XML: {exc}") from exc

    sensor_data = root.find("sensor_data")
    if sensor_data is None:
        raise ValueError(f"{path}: missing <sensor_data>.")

    values: dict[str, float] = {}
    for element in sensor_data:
        text = (element.text or "").strip()
        try:
            value = float(text)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{path}: <{element.tag}> {text!r} is not a finite number."
            ) from exc
        if not is_finite_number(value):
            raise ValueError(
                f"{path}: <{element.tag}> {text!r} is not a finite number."
            )
        values[element.tag] = float(value)

    if not values:
        raise ValueError(f"{path}: <sensor_data> declares no values.")
    return values


def load_preset(
    lamina_id: str, name: str, preset_dir: Path = PRESET_DIR
) -> dict:
    """
    Read one scenario preset and return its metadata plus its values.

    `name` is the file stem, restricted to the same identifier shape as a
    subject so it cannot name a path.  A file for another lamina is reported
    as unknown rather than loaded, because a state that belongs to a different
    model would otherwise be applied to this one's sensors.
    """
    if not isinstance(name, str) or not _NAME_PATTERN.match(name):
        raise ValueError(
            f"Invalid preset name {name!r}: use 1-32 lowercase letters, "
            f"digits or underscores (for example 'walk' or 'rest_1')."
        )

    base = Path(preset_dir)
    resolved_base = base.resolve()
    available = [preset["name"] for preset in list_presets(lamina_id, base)]

    for path in sorted(base.glob("**/*.xml")) if base.is_dir() else []:
        if path.stem != name:
            continue

        resolved = path.resolve()
        try:
            resolved.relative_to(resolved_base)
        except ValueError as exc:
            raise ValueError(
                f"{resolved}: refusing to read a preset outside {base}."
            ) from exc

        try:
            metadata = _metadata_of(path)
        except (OSError, ValueError) as exc:
            raise ValueError(
                f"{path}: cannot read scenario preset: {exc}"
            ) from exc

        if metadata["lamina"] != lamina_id:
            continue

        return {
            "name": name,
            "label": metadata["label"],
            "description": metadata["description"],
            "subject": metadata["subject"],
            "order": metadata["order"],
            "values": _read_values(path),
        }

    raise UnknownPreset(lamina_id, name, available)
