import zmq
import threading
import queue
import time
from ..profiling import logger, profiler  # ←余計なら print に置き換えてもOK
from ..ipc_utils import write_port, read_port
from ..constants import APP_FILE_NAME

HEARTBEAT_INTERVAL = 5    # Subscriber が送る間隔 [秒]
HEARTBEAT_TIMEOUT = 15     # Broker が切断と判断するまでの猶予 [秒]
DEFAULT_PORT = 57556

def get_broker_address():
    port = read_port()
    if port is None:
        port = DEFAULT_PORT
    return f"tcp://localhost:{port}"

class ZMQBroker:
    def __init__(self, bind_addr: str | None = None):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.ROUTER)

        if bind_addr is None:
            port = read_port()
            if port is None:
                port = DEFAULT_PORT
            try:
                self.socket.bind(f"tcp://localhost:{port}")
                self.bind_addr = f"tcp://localhost:{port}"
                logger.info(f"Broker bound to port: {port}")
            except zmq.ZMQError:
                # バインドできなければランダムポート
                port = self.socket.bind_to_random_port("tcp://localhost")
                self.bind_addr = f"tcp://localhost:{port}"
                logger.info(f"Broker bound to random port: {port}")
            write_port(port)

        else:
            # 明示的に指定されている場合
            self.socket.bind(bind_addr)
            self.bind_addr = bind_addr
            try:
                port = int(bind_addr.rsplit(":", 1)[1])
                write_port(port)
            except Exception:
                pass

        self._clients = {}  # ident: (role, last_seen)
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._broker_loop, daemon=True)
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._thread.start()
        self._cleanup_thread.start()
        logger.info("Broker start")

    def _broker_loop(self):
        while not self._stop_event.is_set():
            try:
                ident, _, data = self.socket.recv_multipart()
                msg = data.decode()

                if msg.startswith("REGISTER:"):
                    role = msg.split(":", 1)[1]
                    self._clients[ident] = (role, time.time())
                    self.socket.send_multipart([ident, b'', b'ACK'])
                    continue

                if msg == "SUBSCRIBER_COUNT":
                    count = sum(
                        1 for role, _ in self._clients.values() if role == "sub"
                    )
                    self.socket.send_multipart([ident, b'', str(count).encode()])
                    continue

                if msg == "PING":
                    if ident in self._clients:
                        role, _ = self._clients[ident]
                        self._clients[ident] = (role, time.time())
                    continue
                
                if msg == "BYE":
                    if ident in self._clients:
                        logger.info(f"[BROKER] Subscriber {ident.hex()} requested disconnect")
                        self._clients.pop(ident, None)
                    continue

                if ident in self._clients and self._clients[ident][0] == "pub":
                    # 中継処理: 全subscriberに送信
                    for sub_id, (role, _) in self._clients.items():
                        if role == "sub":
                            logger.info(f"[BROKER] sending: {data}")
                            self.socket.send_multipart([sub_id, b'', data])

            except zmq.ZMQError:
                break
            except Exception as e:
                print(f"Broker Error: {e}")

    def _cleanup_loop(self):
        while not self._stop_event.is_set():
            time.sleep(HEARTBEAT_INTERVAL)
            now = time.time()
            to_remove = []
            for ident, (role, last_seen) in list(self._clients.items()):
                if role == "sub" and (now - last_seen) > HEARTBEAT_TIMEOUT:
                    logger.info(f"[BROKER] removing dead subscriber: {ident.hex()}")
                    to_remove.append(ident)
            for ident in to_remove:
                self._clients.pop(ident, None)

    def close(self):
        self._stop_event.set()
        self._thread.join()
        self._cleanup_thread.join()
        self.socket.close()
        self.context.term()


class ZMQPublisher:
    def __init__(self, connect_addr: str | None = None):
        if connect_addr is None:
            connect_addr = get_broker_address()

        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.DEALER)
        self.socket.connect(connect_addr)

        self.socket.send_multipart([b"", b"REGISTER:pub"])
        # ACK待ち
        poller = zmq.Poller()
        poller.register(self.socket, zmq.POLLIN)
        socks = dict(poller.poll(timeout=500))  # 0.5秒待機

        if self.socket in socks:
            frames = self.socket.recv_multipart()
            if len(frames) != 2 or frames[1] != b'ACK':
                raise RuntimeError("ZMQBroker did not acknowledge registration")

        self._queue = queue.Queue()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._send_loop, daemon=True)
        self._thread.start()

    def send(self, topic: str, message: str, table: str):
        self._queue.put(f"{APP_FILE_NAME}:{table}:{topic}:{message}")

    def _send_loop(self):
        while not self._stop_event.is_set():
            try:
                msg = self._queue.get(timeout=0.1)
                self.socket.send_multipart([b"", msg.encode()])
            except queue.Empty:
                continue

    def get_sub_count(self):
        self.socket.send_multipart([b"", b"SUBSCRIBER_COUNT"])
        poller = zmq.Poller()
        poller.register(self.socket, zmq.POLLIN)
        socks = dict(poller.poll(timeout=500))
        if self.socket in socks:
            frames = self.socket.recv_multipart()
            return int(frames[1].decode())
        else:
            return 0

    def close(self):
        self._stop_event.set()
        self._thread.join(timeout=1)
        self.socket.close()
        self.context.term()


class ZMQSubscriber:
    def __init__(self, connect_addr: str | None = None, head_filter=""):
        if connect_addr is None:
            connect_addr = get_broker_address()
            
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.DEALER)
        self.socket.connect(connect_addr)
        self.socket.send_multipart([b"", b"REGISTER:sub"])
        poller = zmq.Poller()
        poller.register(self.socket, zmq.POLLIN)
        socks = dict(poller.poll(timeout=500))
        if self.socket in socks:
            self.socket.recv_multipart()

        if isinstance(head_filter, (list, tuple, set)):
            self._filter = set(head_filter)
        else:
            self._filter = {head_filter}
        self._callback = None
        self._stop_event = threading.Event()
        self._recv_thread = None
        self._hb_thread = None

    def connect_on_message(self, callback):
        self._callback = callback

    def start(self):
        def recv_loop():
            poller = zmq.Poller()
            poller.register(self.socket, zmq.POLLIN)
            while not self._stop_event.is_set():
                events = dict(poller.poll(100))
                if self.socket in events and events[self.socket] == zmq.POLLIN:
                    try:
                        frames = self.socket.recv_multipart()
                    except zmq.ZMQError:
                        break
                    if len(frames) < 2:
                        continue
                    msg = frames[1].decode()
                    if ":" in msg:
                        topic, content = msg.split(":", 1)
                        if "" in self._filter or topic in self._filter:
                            if self._callback:
                                self._callback(msg)

        def heartbeat_loop():
            while not self._stop_event.is_set():
                self.socket.send_multipart([b"", b"PING"])
                time.sleep(HEARTBEAT_INTERVAL)

        self._recv_thread = threading.Thread(target=recv_loop, daemon=True)
        self._hb_thread = threading.Thread(target=heartbeat_loop, daemon=True)
        self._recv_thread.start()
        self._hb_thread.start()

    def stop(self):
        self._stop_event.set()
        try:
            # 終了通知を送る
            self.socket.send_multipart([b"", b"BYE"])
        except zmq.ZMQError:
            pass  # 通信できなければ無視してPINGで消えるのを待つ

        if self._recv_thread is not None:
            self._recv_thread.join(timeout=1)
        if self._hb_thread is not None:
            self._hb_thread.join(timeout=1)
        try:
            self.socket.close(linger=0)
        except zmq.ZMQError:
            pass
        self.context.term()