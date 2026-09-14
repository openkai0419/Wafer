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
