from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable


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
    timestamp: float = field(compare=True)
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
            timestamp=time.monotonic(),
            operation=operation,
            data=data,
            on_complete=on_complete,
        )
