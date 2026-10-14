import numpy as np
import pytest

from extensions.mapping import projection


def split_by_x(space, min_cluster_size, min_samples):
    if len(space) < 3:
        return np.full(len(space), -1, dtype=np.int32)
    x = space[:, 0]
    return (x > x.mean()).astype(np.int32)


@pytest.fixture()
def fake_cluster(monkeypatch):
    monkeypatch.setattr(projection, "cluster", split_by_x)
