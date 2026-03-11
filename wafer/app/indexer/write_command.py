from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any, Callable

_seq_counter = itertools.count()


class WritePriority:
    REALTIME = 0
    SCAN = 10
    COLLECTION = 20
    DISPATCH = 30
    RETRY = 40
    MAINTENANCE = 50


@dataclass(order=True)
class WriteCommand:
    priority: int
    _seq: int = field(compare=True)
    operation: str = field(compare=False)
    data: dict[str, Any] | None = field(default=None, compare=False, repr=False)
    on_complete: Callable[[], None] | None = field(default=None, compare=False, repr=False)

    @classmethod
    def create(
        cls,
        operation: str,
        priority: int = WritePriority.SCAN,
        data: dict[str, Any] | None = None,
        on_complete: Callable[[], None] | None = None,
    ) -> WriteCommand:
        return cls(
            priority=priority,
            _seq=next(_seq_counter),
            operation=operation,
            data=data,
            on_complete=on_complete,
        )
