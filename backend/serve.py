"""
Start the API on a chosen lamina.

    python serve.py                 # circulatory (the default)
    python serve.py respiratory     # respiratory
    python serve.py path/to/any.xml # anything else
    python serve.py respiratory 8001

The lamina is selected by the CARDIOTWIN_LAMINA environment variable, which
this script sets before importing the app.  A launcher exists because
`.claude/launch.json` has no way to pass an environment variable, and because
`CARDIOTWIN_LAMINA=… uvicorn …` is a bash idiom that does not work in
PowerShell — the two shells disagree about the one line anybody actually wants
to type.

Only the backend changes.  The 2D view builds itself from /api/schema and names
no attribute of its own, so the browser needs a reload and nothing more.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).parent


def resolve(name: str) -> Path:
    """Accept a short name, a filename, or a path to any lamina XML."""
    candidates = [
        Path(name),
        HERE / name,
        HERE / f"{name}.xml",
        HERE / f"{name}_lamina.xml",
    ]
    for path in candidates:
        if path.is_file():
            return path.resolve()

    available = sorted(p.stem.replace("_lamina", "") for p in HERE.glob("*_lamina.xml"))
    raise SystemExit(
        f"No lamina named '{name}'.\n"
        f"Available: {', '.join(available)}\n"
        f"Or pass a path to any lamina XML."
    )


def main() -> None:
    args = [a for a in sys.argv[1:] if a]
    name = args[0] if args else "circulatory"
    port = int(args[1]) if len(args) > 1 else 8000

    lamina = resolve(name)
    os.environ["CARDIOTWIN_LAMINA"] = str(lamina)

    # Imported after the environment is set: main.py reads it at module scope.
    sys.path.insert(0, str(HERE))
    from laminae import lamina_id_of

    print(f"[serve] lamina {lamina.name} ({lamina_id_of(lamina)}) on port {port}")

    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
