"""Run the Pluma API server: ``python -m pluma.api``.

Binds to 127.0.0.1:8000 — loopback only. The default deployment treats
loopback as the security boundary (see ``auth.py``). The API key is
generated/loaded at startup and printed once to stderr.
"""

from __future__ import annotations

import sys

HOST = "127.0.0.1"
PORT = 8000


def main() -> int:
    try:
        import uvicorn
    except ModuleNotFoundError:
        print(
            "pluma.api requires the optional API extra. Install with:\n"
            '    pip install "pluma[api]"',
            file=sys.stderr,
        )
        return 1

    print(
        f"[pluma-api] starting on http://{HOST}:{PORT} (loopback only)",
        file=sys.stderr,
    )
    uvicorn.run("pluma.api.server:app", host=HOST, port=PORT, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
