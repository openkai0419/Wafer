from __future__ import annotations

import asyncio
import json

from aiohttp import WSMsgType, web

from wafer.core.ipc.node import Node
from wafer.core.logs import AppLogger

RELAY_TOPICS = ("update", "folderchanged", "progress", "maximum", "db.created", "db.deleted", "tags.updated")

routes = web.RouteTableDef()


class EventHub:
    def __init__(self, on_app_shutdown=None, on_dev_log=None):
        self.clients: set[web.WebSocketResponse] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.node: Node | None = None
        self.pending: set[asyncio.Task] = set()
        self.on_app_shutdown = on_app_shutdown
        self.on_dev_log = on_dev_log

    def start_node(self):
        self.loop = asyncio.get_running_loop()
        node = Node("webui")
        for topic in RELAY_TOPICS:
            node.subscribe(topic, self.make_relay(topic))
        if self.on_app_shutdown is not None:
            node.subscribe("app.shutdown", self._on_shutdown_message)
        if self.on_dev_log is not None:
            node.subscribe("dev.log", self._relay_dev_log)
        node.start()
        self.node = node
        AppLogger.set_node(node)
        AppLogger.info("WebUI event hub connected to IPC.")

    def _relay_dev_log(self, msg):
        p = msg.payload
        if isinstance(p, dict):
            self.on_dev_log(p.get("level", "info"), p.get("text", ""), msg.source, msg.db or "")
        return True

    def _on_shutdown_message(self, msg):
        AppLogger.info("WebUI received app.shutdown.")
        self.on_app_shutdown()
        return True

    def make_relay(self, topic: str):
        def handler(msg):
            payload = msg.payload
            if not isinstance(payload, (str, int, float, bool, list, dict, type(None))):
                payload = str(payload)
            data = json.dumps({"topic": topic, "db": msg.db or "", "payload": payload})
            if self.loop is not None:
                self.loop.call_soon_threadsafe(self.broadcast, data)
            return True

        return handler

    def broadcast(self, data: str):
        for ws in list(self.clients):
            task = asyncio.ensure_future(self.send_safe(ws, data))
            self.pending.add(task)
            task.add_done_callback(self.pending.discard)

    async def send_safe(self, ws: web.WebSocketResponse, data: str):
        try:
            await ws.send_str(data)
        except (ConnectionResetError, RuntimeError) as e:
            self.clients.discard(ws)
            AppLogger.debug(f"WebUI websocket send failed, client dropped: {e}")

    async def close(self):
        if self.node is not None:
            self.node.stop()
            self.node = None
        for ws in list(self.clients):
            await ws.close()
        self.clients.clear()


EVENT_HUB = web.AppKey("event_hub", EventHub)


@routes.get("/ws")
async def websocket_handler(request: web.Request):
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    hub = request.app[EVENT_HUB]
    hub.clients.add(ws)
    try:
        async for msg in ws:
            if msg.type == WSMsgType.ERROR:
                break
    finally:
        hub.clients.discard(ws)
    return ws
