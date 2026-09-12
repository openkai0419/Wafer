"""Shared web-serving primitives for Wafer.

This namespace holds building blocks that turn Wafer's core capabilities into
things a web front end can serve, independent of any particular transport
(aiohttp/FastAPI/...) or database schema. Both the bundled local WebUI
(``wafer.app.webui``) and out-of-tree services build on top of these.

Contract for everything under ``wafer.web``:

* **Transport-agnostic** — no aiohttp/FastAPI request objects in the public
  surface; callers pass plain paths/bytes and get plain values back.
* **DB-agnostic** — nothing here assumes the local SQLite file-DB schema.
* **Qt-free at import time** — importing any module under ``wafer.web`` must not
  pull in PySide6/shiboken6. Modules that need a plugin resolver (which does
  import Qt) do so with a function-local import, so the module stays importable
  in a headless server process. See ``tests-unit/wafer/web/media/test_no_qt_import.py``.
"""
