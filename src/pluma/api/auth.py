"""API-key generation, persistence, and the FastAPI verify dependency.

# The default Docker deployment binds 127.0.0.1:8000 — loopback is the
# real security boundary. This auth check exists for spec compliance and
# to support non-loopback deployments (CI, integration tests, future hosting).

Key lifecycle:

* If ``PLUMA_API_KEY`` is set in the environment, that value is the key
  verbatim (no file is written). This is the CI / integration-test /
  fixed-deployment path.
* Otherwise the key is read from a file if one exists, else generated and
  persisted. The file is ``$PLUMA_KEY_FILE`` if set, else
  ``/var/lib/pluma/key`` when ``/var/lib/pluma`` exists (the Docker
  layout), else ``~/.pluma/key``.

The key is printed to stderr exactly once, the first time it is loaded
in this process (``init_api_key``), and never logged again.
"""

from __future__ import annotations

import os
import secrets
import sys
import threading
from pathlib import Path
from typing import Optional

from fastapi import Header

# Crockford base32 — no I/L/O/U. Matches the spec's ULID-shaped patterns.
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_KEY_PREFIX = "plm_"
_KEY_BODY_LEN = 24

_lock = threading.Lock()
_api_key: Optional[str] = None
_announced = False


class AuthError(Exception):
    """Raised by ``verify_api_key`` on a missing or wrong key.

    The server's exception handler turns this into a spec-shaped 401
    ``unauthorized`` error body.
    """


def _crockford_token(n: int = _KEY_BODY_LEN) -> str:
    return "".join(secrets.choice(_CROCKFORD) for _ in range(n))


def generate_api_key() -> str:
    """A fresh ``plm_``-prefixed Crockford ULID-shaped key."""
    return _KEY_PREFIX + _crockford_token()


def _key_file_path() -> Path:
    override = os.environ.get("PLUMA_KEY_FILE")
    if override:
        return Path(override)
    # /var/lib/pluma exists only in the Docker image (the Dockerfile
    # creates it). Outside Docker, fall back to the user's home.
    if Path("/var/lib/pluma").is_dir():
        return Path("/var/lib/pluma/key")
    return Path.home() / ".pluma" / "key"


def _load_or_create_key() -> str:
    """Return the env key, an on-disk key, or a freshly persisted one."""
    env_key = os.environ.get("PLUMA_API_KEY")
    if env_key:
        return env_key

    path = _key_file_path()
    try:
        if path.is_file():
            existing = path.read_text(encoding="utf-8").strip()
            if existing:
                return existing
    except OSError:
        # Unreadable key file → fall through and mint a new in-memory key
        # rather than refusing to boot.
        pass

    key = generate_api_key()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(key, encoding="utf-8")
        os.chmod(path, 0o600)
    except OSError as e:
        print(
            f"[pluma-api] warning: could not persist API key to {path}: {e}. "
            "Key is valid for this process only.",
            file=sys.stderr,
        )
    return key


def init_api_key() -> str:
    """Load (or create) the key and announce it on stderr exactly once.

    Safe to call repeatedly; the announcement and the load happen only on
    the first call in this process.
    """
    global _api_key, _announced
    with _lock:
        if _api_key is None:
            _api_key = _load_or_create_key()
        if not _announced:
            print(
                f"[pluma-api] API key: {_api_key}\n"
                "[pluma-api] Send it in the X-Pluma-Key header on every "
                "request except GET /v1/healthz.",
                file=sys.stderr,
                flush=True,
            )
            _announced = True
        return _api_key


def get_api_key() -> str:
    """The loaded key, initializing (without re-announcing) if needed."""
    if _api_key is None:
        return init_api_key()
    return _api_key


async def verify_api_key(
    x_pluma_key: Optional[str] = Header(default=None, alias="X-Pluma-Key"),
) -> None:
    """FastAPI dependency: constant-time compare of ``X-Pluma-Key``.

    Raises :class:`AuthError` (→ 401 ``unauthorized``) when the header is
    absent or does not match the loaded key.
    """
    expected = get_api_key()
    if x_pluma_key is None or not secrets.compare_digest(
        x_pluma_key, expected
    ):
        raise AuthError("Missing or invalid X-Pluma-Key header")
