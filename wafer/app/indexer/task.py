from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass, field
from typing import Callable

_seq_counter = itertools.count()


class TaskPriority:
    SHUTDOWN = -1
    REALTIME = 0
    SCAN = 10
    COLLECTION = 20
    DISPATCH = 30
    RETRY = 40
    MAINTENANCE = 50


class CancelToken:

    def __init__(self):
        self._cancelled = threading.Event()

    def cancel(self):
        self._cancelled.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()


@dataclass(order=True)
class Task:
    priority: int
    _seq: int = field(compare=True)
    name: str = field(compare=False)
    run: Callable[[], None] = field(compare=False, repr=False)
    cancel_token: CancelToken | None = field(default=None, compare=False, repr=False)
    on_complete: Callable[[], None] | None = field(default=None, compare=False, repr=False)

    @classmethod
    def create(
        cls,
        name: str,
        *,
        priority: int = TaskPriority.SCAN,
        run: Callable[[], None] = lambda: None,
        cancel_token: CancelToken | None = None,
        on_complete: Callable[[], None] | None = None,
    ) -> Task:
        return cls(
            priority=priority,
            _seq=next(_seq_counter),
            name=name,
            run=run,
            cancel_token=cancel_token,
            on_complete=on_complete,
        )
