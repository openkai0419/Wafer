import asyncio
import os
import shutil

import pytest

from test_support.webui_dataset import DB_NAME


@pytest.fixture
def db_copy(dataset, monkeypatch, tmp_path):
    from wafer.app.webui.backend import session

    target = tmp_path / f"{DB_NAME}.db"
    shutil.copy(dataset["root"] / "data" / f"{DB_NAME}.db", target)
    monkeypatch.setattr(session, "data_db_path", lambda name: str(target))
    monkeypatch.setattr(session, "list_data_db_names", lambda: [DB_NAME])
    return target


def test_release_db_closes_connections_so_the_file_can_be_deleted(db_copy):
    from wafer.app.webui.backend.session import QueryService

    async def scenario():
        service = QueryService()
        session = await service.execute(DB_NAME, [], "none", True)
        await service.keys(DB_NAME)
        service.release_db(DB_NAME)
        while service._closing:
            await asyncio.sleep(0.01)
        os.remove(db_copy)
        with pytest.raises(KeyError):
            service.db(DB_NAME)
        assert service.session(session.query_id) is None
        await service.close()

    asyncio.run(scenario())


def test_restore_db_reopens_a_db_whose_delete_failed(db_copy):
    from wafer.app.webui.backend.session import QueryService

    async def scenario():
        service = QueryService()
        await service.execute(DB_NAME, [], "none", True)
        service.release_db(DB_NAME)
        service.restore_db(DB_NAME)
        session = await service.execute(DB_NAME, [], "none", True)
        await service.close()
        return session.total

    assert asyncio.run(scenario()) == 5


def test_lookup_file_reports_a_file_missing_on_disk(db_copy, dataset, monkeypatch):
    from wafer.app.webui.backend.session import DbService

    service = DbService(DB_NAME)
    path = dataset["files"][0][0]
    try:
        assert service.lookup_file(path)[2] is not None

        def missing(p, *args, **kwargs):
            raise FileNotFoundError(p)

        monkeypatch.setattr("wafer.app.webui.backend.session.os.stat", missing)
        logical, source, found = service.lookup_file(path)
        assert (logical, source, found) == (path, path, None)
    finally:
        service.close()
