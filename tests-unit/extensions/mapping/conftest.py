import numpy as np
import pytest

from extensions.mapping import projection
from extensions.mapping.view_settings import ViewSettings
from wafer.plugin.grid.thumbnail_loader import shared_image_cache


def split_by_x(space, min_cluster_size, min_samples):
    if len(space) < 3:
        return np.full(len(space), -1, dtype=np.int32)
    x = space[:, 0]
    return (x > x.mean()).astype(np.int32)


@pytest.fixture()
def fake_cluster(monkeypatch):
    monkeypatch.setattr(projection, "cluster", split_by_x)


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
