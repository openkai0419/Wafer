import asyncio
import json
from types import SimpleNamespace

from wafer.app.webui.backend.events import EVENT_HUB


def test_websocket_receives_relayed_event(client, app):
    hub = app[EVENT_HUB]

    async def scenario():
        ws = await client.raw.ws_connect("/ws")
        hub.loop = asyncio.get_running_loop()
        relay = hub.make_relay("update")
        assert relay(SimpleNamespace(payload=None, db="testdb")) is True
        received = await asyncio.wait_for(ws.receive_str(), timeout=5)
        await ws.close()
        return received

    data = json.loads(client.loop.run_until_complete(scenario()))
    assert data == {"topic": "update", "db": "testdb", "payload": None}


def test_relay_stringifies_unknown_payload(client, app):
    hub = app[EVENT_HUB]

    async def scenario():
        ws = await client.raw.ws_connect("/ws")
        hub.loop = asyncio.get_running_loop()
        relay = hub.make_relay("progress")
        relay(SimpleNamespace(payload=object(), db=""))
        received = await asyncio.wait_for(ws.receive_str(), timeout=5)
        await ws.close()
        return received

    data = json.loads(client.loop.run_until_complete(scenario()))
    assert data["topic"] == "progress"
    assert isinstance(data["payload"], str)


def test_closed_client_removed(client, app):
    hub = app[EVENT_HUB]

    async def scenario():
        ws = await client.raw.ws_connect("/ws")
        await ws.close()
        await asyncio.sleep(0.05)
        return len(hub.clients)

    assert client.loop.run_until_complete(scenario()) == 0


def test_db_deleting_releases_the_db_and_db_deleted_restores_it():
    from wafer.app.webui.backend.events import EventHub

    calls = []

    async def scenario():
        hub = EventHub(on_db_deleting=lambda name: calls.append(("release", name)), on_db_deleted=lambda name: calls.append(("restore", name)))
        hub.loop = asyncio.get_running_loop()
        assert hub._on_db_deleting(SimpleNamespace(payload="foo", db="foo")) is True
        hub.make_relay("db.deleted")(SimpleNamespace(payload="foo", db="foo"))
        while len(calls) < 2:
            await asyncio.sleep(0.01)

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))
    assert calls == [("release", "foo"), ("restore", "foo")]


def test_server_wires_db_deleting_to_the_query_service(app):
    from wafer.app.webui.backend.session import QUERY_SERVICE

    hub = app[EVENT_HUB]
    service = app[QUERY_SERVICE]
    assert hub.on_db_deleting == service.release_db
    assert hub.on_db_deleted == service.restore_db
