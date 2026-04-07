from __future__ import annotations

from random import shuffle

from ..plugin.query.base import BaseSortPlugin
from ..utils.formatting import natural_key


class NaturalPathSort(BaseSortPlugin):
    NAME = "path"
    PRIORITY = 100

    @classmethod
    def sort_rows(cls, rows, ascending):
        rows.sort(key=lambda r: natural_key(r["path"] or ""), reverse=not ascending)
        return rows


class NaturalNameSort(BaseSortPlugin):
    NAME = "name"
    PRIORITY = 90
    META_KEY = "name"

    @classmethod
    def sort_rows(cls, rows, ascending):
        rows.sort(key=lambda r: natural_key(r["name"] or ""), reverse=not ascending)
        return rows


class ModifiedSort(BaseSortPlugin):
    NAME = "modified"
    PRIORITY = 80
    META_KEY = "modified"


class CreatedSort(BaseSortPlugin):
    NAME = "created"
    PRIORITY = 70
    META_KEY = "created"


class SizeSort(BaseSortPlugin):
    NAME = "size"
    PRIORITY = 60
    META_KEY = "size"


class CollectedSort(BaseSortPlugin):
    NAME = "collected"
    PRIORITY = 50
    META_KEY = "collected"


class RandomSort(BaseSortPlugin):
    NAME = "random"
    PRIORITY = 0

    @classmethod
    def sort_rows(cls, rows, ascending):
        shuffle(rows)
        return rows
