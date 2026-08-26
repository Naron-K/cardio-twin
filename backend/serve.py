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

This sets the *default* lamina — what a request that names none will get.  It
is no longer the only way to change lamina: the 2D view has a picker, and both
/api/schema and /ws/feedback take a `lamina` id per request, so switching does
not need a restart and two tabs can hold two laminae at once.  What this script
still decides is where a bare `#twin` lands.
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
