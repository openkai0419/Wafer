import zmq
import threading
import queue
from ..profiling import logger, profiler

class ZMQBroker:
    def __init__(self, bind_addr="tcp://localhost:57556"):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.ROUTER)
        self.socket.bind(bind_addr)

        self._clients = {}  # ident: type ('pub' or 'sub')
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._broker_loop, daemon=True)
        self._thread.start()
        logger.info("Broker start")

    def _broker_loop(self):
        while not self._stop_event.is_set():
            try:
                ident, _, data = self.socket.recv_multipart()
                msg = data.decode()

                if msg.startswith("REGISTER:"):
                    role = msg.split(":", 1)[1]
                    self._clients[ident] = role
                    self.socket.send_multipart([ident, b'', b'ACK'])
                    continue

                if ident in self._clients and self._clients[ident] == "pub":
                    # 中継処理: 全subscriberに送信
                    for sub_id, role in self._clients.items():
                        if role == "sub":
                            logger.info(data)
                            self.socket.send_multipart([sub_id, b'', data])

            except zmq.ZMQError:
                break  # 終了要求
            except Exception as e:
                print(f"Broker Error: {e}")

    def close(self):
        self._stop_event.set()
        self._thread.join()
        self.socket.close()
        self.context.term()

class ZMQPublisher:
    def __init__(self, connect_addr="tcp://localhost:57556"):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.DEALER)
        self.socket.connect(connect_addr)
        self.socket.send(b"REGISTER:pub")
        poller = zmq.Poller()
        poller.register(self.socket, zmq.POLLIN)
        socks = dict(poller.poll(timeout=500))  # 0.5秒待機

        if self.socket in socks:
            ack = self.socket.recv()
            if ack != b'ACK':
                raise RuntimeError("ZMQBroker did not acknowledge registration")

        self._queue = queue.Queue()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._send_loop, daemon=True)
        self._thread.start()

    def send(self, topic: str, message: str):
        logger.info(f"[SEND]{topic}, {message}")
        self._queue.put(f"{topic}:{message}")

    def _send_loop(self):
        while not self._stop_event.is_set():
            try:
                msg = self._queue.get(timeout=0.1)
                self.socket.send_string(msg)
            except queue.Empty:
                continue

    def close(self):
        self._stop_event.set()
        self._thread.join(timeout=1)
        self.socket.close()
        self.context.term()

class ZMQSubscriber:
    def __init__(self, connect_addr="tcp://localhost:57556", topic_filter=""):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.DEALER)
        self.socket.connect(connect_addr)
        self.socket.send(b"REGISTER:sub")

        if isinstance(topic_filter, (list, tuple, set)):
            self._filter = set(topic_filter)
        else:
            self._filter = {topic_filter}
        self._callback = None
        self._stop_event = threading.Event()
        self._thread = None

    def connect_on_message(self, callback):
        self._callback = callback

    def start(self):
        def loop():
            poller = zmq.Poller()
            poller.register(self.socket, zmq.POLLIN)
            while not self._stop_event.is_set():
                events = dict(poller.poll(100))
                if self.socket in events and events[self.socket] == zmq.POLLIN:
                    try:
                        msg = self.socket.recv_string()
                    except zmq.ZMQError:
                        break 
                    if ":" in msg:
                        topic, content = msg.split(":", 1)
                        if "" in self._filter or topic in self._filter:
                            if self._callback:
                                self._callback(msg)
        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
        try:
            self.socket.close(linger=0)  # lingerを明示的に設定して即切断
        except zmq.ZMQError:
            pass
        self.context.term()
