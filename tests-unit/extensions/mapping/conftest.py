import numpy as np
import pytest

from extensions.mapping import projection
from extensions.mapping.params import Grouping
from extensions.mapping import view_settings
from extensions.mapping.view_settings import GroupingStore, ViewSettings
from wafer.plugin.grid.thumbnail_loader import shared_image_cache


def split_by_x(space, min_cluster_size, min_samples, method="eom"):
    if len(space) < 3:
        return np.full(len(space), -1, dtype=np.int32)
    x = space[:, 0]
    return (x > x.mean()).astype(np.int32)


class SplitByXTree:
    def __init__(self, space, min_samples):
        self.space = space

    def labels(self, min_cluster_size, method="eom"):
        return split_by_x(self.space, min_cluster_size, 0)


@pytest.fixture()
def fake_cluster(monkeypatch):
    monkeypatch.setattr(projection, "cluster", split_by_x)
    monkeypatch.setattr(projection, "ClusterTree", SplitByXTree)


@pytest.fixture(autouse=True)
def empty_shared_image_cache():
    shared_image_cache().clear()
    yield
    shared_image_cache().clear()


@pytest.fixture(autouse=True)
def no_layout_warm_up(monkeypatch):
    monkeypatch.setattr(projection, "_warmed_up", True)


@pytest.fixture(autouse=True)
def fresh_view_settings(monkeypatch):
    monkeypatch.setattr(ViewSettings, "_instance", None)


@pytest.fixture(autouse=True)
def fresh_grouping_store(monkeypatch):
    saved = {}
    monkeypatch.setattr(GroupingStore, "_instance", None)
    monkeypatch.setattr(view_settings, "load_grouping", lambda db_name: saved.get(db_name, Grouping()))
    monkeypatch.setattr(view_settings, "save_grouping", lambda db_name, grouping: saved.__setitem__(db_name, grouping))
    return saved


@pytest.fixture(autouse=True)
def every_database_can_open(monkeypatch):
    from extensions.mapping.space_panel import MappingSpaceWidget

    monkeypatch.setattr(MappingSpaceWidget, "can_open", lambda self, db_name: True)
