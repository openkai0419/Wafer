from __future__ import annotations
import uuid
from typing import Any

import msgpack

from ...utils.logs import AppLogger
from .transport import Priority


class Message:
    __slots__ = ("coalesce", "db", "destination", "payload", "priority", "request_id", "source", "topic")

    def __init__(self, topic: str, source: str, destination: str, db: str, payload: Any, request_id: str | None, priority: int = Priority.MID, coalesce: bool = False):
        self.topic = topic
        self.source = source
        self.destination = destination
        self.db = db
        self.payload = payload
        self.request_id = request_id
        self.priority = priority
        self.coalesce = coalesce

    @classmethod
    def build(cls, topic: str, payload: Any = None, *, src: str = "", dst: str = "ALL", db: str = "", rid: str | None = None, priority: int = Priority.MID, coalesce: bool = False) -> Message:
        return cls(topic, src, dst, db, payload, rid, priority, coalesce)

    def to_frames(self) -> tuple[bytes, bytes]:
        header = {"t": self.topic, "s": self.source, "d": self.destination, "db": self.db}
        if self.request_id:
            header["r"] = self.request_id
        if self.priority != Priority.MID:
            header["p"] = self.priority
        if self.coalesce:
            header["c"] = True
        return (msgpack.packb(header, use_bin_type=True), msgpack.packb(self.payload, use_bin_type=True))

    @classmethod
    def from_frames(cls, frames: list[bytes] | tuple[bytes, ...]) -> Message | None:
        if len(frames) < 2:
            return None
        try:
            header = msgpack.unpackb(frames[0], raw=False)
            payload = msgpack.unpackb(frames[1], raw=False)
        except Exception as e:
            AppLogger.debug(f"Message.from_frames failed: {e}")
            return None
        return cls(
            topic=header.get("t", ""),
            source=header.get("s", ""),
            destination=header.get("d", "ALL"),
            db=header.get("db", ""),
            payload=payload,
            request_id=header.get("r"),
            priority=header.get("p", Priority.MID),
            coalesce=header.get("c", False),
        )

    def reply(self, payload: Any = None, *, topic: str | None = None) -> Message:
        return Message(
            topic=topic or self.topic,
            source=self.destination,
            destination=self.source,
            db=self.db,
            payload=payload,
            request_id=self.request_id,
            priority=self.priority,
            coalesce=self.coalesce,
        )

    @staticmethod
    def make_request_id(prefix: str = "") -> str:
        return f"{prefix}{uuid.uuid4().hex[:12]}"
