from __future__ import annotations

import re
from random import shuffle

from ..plugin.query.base import BaseSortPlugin


_NUM_SPLIT = re.compile(r'(\d+)').split


def _natural_key(s):
    return [int(c) if c.isdigit() else c.casefold() for c in _NUM_SPLIT(s)]


class NaturalPathSort(BaseSortPlugin):
    NAME = 'path'
    PRIORITY = 100

    @classmethod
    def sort_rows(cls, rows, ascending):
        rows.sort(key=lambda r: _natural_key(r['path'] or ''), reverse=not ascending)
        return rows

    @classmethod
    def required_columns(cls):
        return ('path',)


class NaturalNameSort(BaseSortPlugin):
    NAME = 'name'
    PRIORITY = 90

    @classmethod
    def sort_rows(cls, rows, ascending):
        rows.sort(key=lambda r: _natural_key(r['name'] or ''), reverse=not ascending)
        return rows

    @classmethod
    def required_columns(cls):
        return ('name',)


class ModifiedSort(BaseSortPlugin):
    NAME = 'modified'
    PRIORITY = 80
    META_KEY = 'modified'


class CreatedSort(BaseSortPlugin):
    NAME = 'created'
    PRIORITY = 70
    META_KEY = 'created'


class SizeSort(BaseSortPlugin):
    NAME = 'size'
    PRIORITY = 60
    META_KEY = 'size'


class CollectedSort(BaseSortPlugin):
    NAME = 'collected'
    PRIORITY = 50
    META_KEY = 'collected'


class RandomSort(BaseSortPlugin):
    NAME = 'random'
    PRIORITY = 0

    @classmethod
    def sort_rows(cls, rows, ascending):
        shuffle(rows)
        return rows
