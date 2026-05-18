"""Pluma HTTP API — a FastAPI dispatcher over the three sister tools.

The package implements the spec in ``openapi.yaml`` (the canonical source
of truth, this directory). Install with the optional extra::

    pip install "pluma[api]"

then run::

    python -m pluma.api          # or the `pluma-api` console script

See ``server.py`` for the app and ``worker.py`` for the source dispatcher.
"""
