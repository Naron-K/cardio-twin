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
from respiratory_lamina import RespiratoryLamina
from universal_twin import UniversalTwin

# The default when nothing overrides it.
DEFAULT_LAMINA = Path(__file__).parent / "circulatory_lamina.xml"

# lamina id (the `id` attribute of <lamina>) → the class holding its maths.
_IMPLEMENTATIONS: dict[str, Type[UniversalTwin]] = {
    "lamina_circulatory": CirculatoryLamina,
    "lamina_respiratory": RespiratoryLamina,
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
