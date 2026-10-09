"""
Lamina loader — which Python implements the lamina this process is running.

`UniversalTwin` reads a lamina XML and resolves each computed attribute by
looking its `computed_by` function id up in `_function_registry`. A subclass
populates that registry: the XML declares *what* is computed and in what order,
the subclass supplies *how*. Functions receive generic positional inputs and
never see an attribute name, so the two halves stay decoupled — but the pairing
still has to be made somewhere.

It used to be made by importing `CirculatoryLamina` at the top of `main.py`,
which meant pointing the backend at a different lamina file loaded that file's
declarations into a class holding a circulation's arithmetic. Every computed
attribute would have logged "no function registered" and stayed unset.

Here instead: the XML's own `id` picks the implementation. A lamina with no
entry still loads — on bare `UniversalTwin`, where every function is missing —
and that is a deliberate outcome rather than a crash. Its structure is intact,
so the visualiser draws the whole model correctly and shows a dash on every
computed node, which is an honest picture of "declared but not implemented".

Adding a lamina: write the XML, write a subclass registering one function per
`<function>`, add one line to `_IMPLEMENTATIONS`.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Type

from circulatory_lamina import CirculatoryLamina
from metabolic_lamina import MetabolicLamina
from respiratory_lamina import RespiratoryLamina
from universal_twin import UniversalTwin

# The default when nothing overrides it.
DEFAULT_LAMINA = Path(__file__).parent / "circulatory_lamina.xml"

# lamina id (the `id` attribute of <lamina>) → the class holding its maths.
_IMPLEMENTATIONS: dict[str, Type[UniversalTwin]] = {
    "lamina_circulatory": CirculatoryLamina,
    "lamina_respiratory": RespiratoryLamina,
    "lamina_metabolic":   MetabolicLamina,
}


def lamina_path() -> Path:
    """
    Which lamina file this process runs.

    `CARDIOTWIN_LAMINA` overrides the default, so "point the backend at a
    different lamina and the visualiser follows" is something anyone can try
    rather than a claim in a document.
    """
    return Path(os.environ.get("CARDIOTWIN_LAMINA") or DEFAULT_LAMINA)


def lamina_id_of(path: Path | str) -> str:
    """Read just the `id` off <lamina> without building a twin."""
    root = ET.parse(str(path)).getroot()
    return root.get("id", "")


def implementation_for(lamina_id: str) -> Type[UniversalTwin]:
    """
    The class registered for this lamina, or bare `UniversalTwin`.

    Falling back rather than raising is the point: an unregistered lamina is
    a model whose arithmetic nobody has written yet, not a broken file, and
    the difference is visible on screen the moment it loads.
    """
    return _IMPLEMENTATIONS.get(lamina_id, UniversalTwin)


def load_twin(path: Path | str | None = None) -> UniversalTwin:
    """Build the twin for a lamina file, choosing its implementation by id."""
    resolved = Path(path) if path is not None else lamina_path()
    return implementation_for(lamina_id_of(resolved))(str(resolved))


# ── Which laminae exist, and how to name one from outside ────────────────────
#
# The process-wide default above answers "what is this backend running".  What
# follows answers a different question — "what could a request ask for" — and
# it is the half that lets the lamina be a property of the connection rather
# than of the process.  Two tabs can then run two laminae at once, and, more to
# the point, a schema and a stream can be guaranteed to have come from the same
# place because both were told the same id.

LAMINA_DIR = Path(__file__).parent


class UnknownLamina(LookupError):
    """A request named a lamina id that no file in `LAMINA_DIR` declares."""

    def __init__(self, lamina_id: str, available: list[str]) -> None:
        self.lamina_id = lamina_id
        self.available = available
        super().__init__(
            f"No lamina with id '{lamina_id}'. Available: {', '.join(available)}"
        )


def available_laminae() -> list[dict]:
    """
    Every lamina file this backend can serve, by id.

    A lamina with no entry in `_IMPLEMENTATIONS` is listed and marked, not
    hidden.  It loads on bare `UniversalTwin`, draws its whole structure and
    shows a dash on every computed node — an honest picture of "declared but
    not implemented", and a legitimate thing to want to look at.  Hiding it
    would make the one case this loader was written to support invisible.
    """
    found: list[dict] = []
    for path in sorted(LAMINA_DIR.glob("*_lamina.xml")):
        try:
            root = ET.parse(str(path)).getroot()
        except ET.ParseError:
            continue  # a malformed file is not an option to offer
        lamina_id = root.get("id", "")
        if not lamina_id:
            continue
        found.append({
            "id":          lamina_id,
            "name":        root.get("name", path.stem),
            "level":       int(root.get("level", "0")),
            "file":        path.name,
            "implemented": lamina_id in _IMPLEMENTATIONS,
        })
    return found


def resolve_lamina(lamina_id: str | None) -> Path:
    """
    The file for a lamina id, or the process default when none is named.

    Resolution is by the XML's own `id`, never by filename, so a URL does not
    depend on where the file sits on disk.  An unknown id raises rather than
    quietly falling back: serving the default to someone who asked for
    something else is precisely the mismatch this whole path exists to stop.
    """
    if not lamina_id:
        return lamina_path()
    for entry in available_laminae():
        if entry["id"] == lamina_id:
            return LAMINA_DIR / entry["file"]
    raise UnknownLamina(lamina_id, [e["id"] for e in available_laminae()])
