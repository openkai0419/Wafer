from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from queue import Empty, PriorityQueue
from typing import Callable

from ...utils.logs import AppLogger
from .db_writer import DatabaseWriter
from .write_command import WriteCommand, WritePriority

_QUEUE_POLL_INTERVAL = 1.0
_IDLE_THRESHOLD = 300.0
_STOP_PRIORITY = 999


@dataclass
class PeriodicTask:
    name: str
    interval: float
    create_command: Callable[[], WriteCommand]
    idle_only: bool = False
    last_run: float = field(default=0.0)

    def should_run(self, now: float, is_idle: bool) -> bool:
        if self.idle_only and not is_idle:
            return False
        return (now - self.last_run) >= self.interval


class TaskScheduler:

    def __init__(self, writer: DatabaseWriter):
        self._writer = writer
        self._queue: PriorityQueue[WriteCommand] = PriorityQueue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_active_time = time.monotonic()
        self._idle_threshold = _IDLE_THRESHOLD
        self._periodic_tasks: list[PeriodicTask] = []

    @property
    def writer(self) -> DatabaseWriter:
        return self._writer

    def submit(self, command: WriteCommand):
        self._queue.put(command)

    def add_periodic_task(self, task: PeriodicTask):
        self._periodic_tasks.append(task)

    def start(self):
        self._writer.start()
        self._writer.initialize()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.submit(WriteCommand.create('__stop__', priority=_STOP_PRIORITY))
        if self._thread:
            self._thread.join(timeout=10.0)
        self._stop.set()
        self._writer.close()

    def _loop(self):
        while not self._stop.is_set():
            self._check_periodic_tasks()
            try:
                cmd = self._queue.get(timeout=_QUEUE_POLL_INTERVAL)
            except Empty:
                continue
            if cmd.operation == '__stop__':
                break
            self._writer.execute(cmd)
            if cmd.on_complete:
                try:
                    cmd.on_complete()
                except Exception as e:
                    AppLogger.warning(
                        f'[Scheduler] on_complete callback failed for {cmd.operation}: {e}', exc=e,
                    )
            if cmd.priority <= WritePriority.SCAN:
                self._last_active_time = time.monotonic()

    def _check_periodic_tasks(self):
        now = time.monotonic()
        is_idle = (now - self._last_active_time) >= self._idle_threshold
        for task in self._periodic_tasks:
            if task.should_run(now, is_idle):
                self.submit(task.create_command())
                task.last_run = now
