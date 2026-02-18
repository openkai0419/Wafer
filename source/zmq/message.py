from __future__ import annotations
import uuid
from typing import Any

import msgpack

from ..common.logs import AppLogger
from .transport import Priority


class Msg:
    __slots__ = ('topic', 'src', 'dst', 'db', 'payload', 'rid', 'priority', 'coalesce')

    def __init__(self, topic: str, src: str, dst: str, db: str, payload: Any,
                 rid: str | None, priority: int = Priority.MID, coalesce: bool = False):
        self.topic = topic
        self.src = src
        self.dst = dst
        self.db = db
        self.payload = payload
        self.rid = rid
        self.priority = priority
        self.coalesce = coalesce

    @classmethod
    def build(cls, topic: str, payload: Any = None, *, src: str = '', dst: str = 'ALL',
              db: str = '', rid: str | None = None, priority: int = Priority.MID,
              coalesce: bool = False) -> Msg:
        return cls(topic, src, dst, db, payload, rid, priority, coalesce)

    def to_frames(self) -> tuple[bytes, bytes]:
        header = {'t': self.topic, 's': self.src, 'd': self.dst, 'db': self.db}
        if self.rid:
            header['r'] = self.rid
        if self.priority != Priority.MID:
            header['p'] = self.priority
        if self.coalesce:
            header['c'] = True
        return (msgpack.packb(header, use_bin_type=True), msgpack.packb(self.payload, use_bin_type=True))

    @classmethod
    def from_frames(cls, frames: list[bytes] | tuple[bytes, ...]) -> Msg | None:
        if len(frames) < 2:
            return None
        try:
            header = msgpack.unpackb(frames[0], raw=False)
            payload = msgpack.unpackb(frames[1], raw=False)
        except Exception as e:
            AppLogger.debug(f'Msg.from_frames failed: {e}')
            return None
        return cls(
            topic=header.get('t', ''),
            src=header.get('s', ''),
            dst=header.get('d', 'ALL'),
            db=header.get('db', ''),
            payload=payload,
            rid=header.get('r'),
            priority=header.get('p', Priority.MID),
            coalesce=header.get('c', False),
        )

    def reply(self, payload: Any = None, *, topic: str | None = None) -> Msg:
        return Msg(
            topic=topic or self.topic,
            src=self.dst,
            dst=self.src,
            db=self.db,
            payload=payload,
            rid=self.rid,
            priority=self.priority,
            coalesce=self.coalesce,
        )

    @staticmethod
    def make_rid(prefix: str = '') -> str:
        return f'{prefix}{uuid.uuid4().hex[:12]}'
