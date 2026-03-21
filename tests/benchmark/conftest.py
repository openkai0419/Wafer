import pytest


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "benchmark" in str(item.fspath):
            item.add_marker(pytest.mark.benchmark)
