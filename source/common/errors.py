from __future__ import annotations

from typing import Any
import sys

from .profiling import logger


def raise_error(parent: Any, text: str, title: str = "Error") -> None:
    if title:
        print(f"{title}: {text}", file=sys.stderr)
    else:
        print(str(text), file=sys.stderr)
    try:
        if logger is not None:
            logger.error(f"{title}: {text}" if title else str(text))
    except Exception:
        pass
    raise RuntimeError(text)


def show_warning(parent: Any, text: str, title: str = "Warning", exc: BaseException | None = None) -> None:
    if title:
        print(f"{title}: {text}", file=sys.stderr)
    else:
        print(str(text), file=sys.stderr)
    try:
        if logger is not None:
            logger.warning(f"{title}: {text}" if title else str(text), exc_info=exc)
    except Exception:
        pass
    if exc is None:
        return
    try:
        import traceback

        print("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)), file=sys.stderr)
    except Exception:
        try:
            print(repr(exc), file=sys.stderr)
        except Exception:
            pass
