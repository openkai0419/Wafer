import zmq
import threading
import queue

class ZMQPublisher_Old:
    def __init__(self, bind_addr="tcp://localhost:7556"):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.bind(bind_addr)

    def send(self, topic: str, message: str):
        full_msg = f"{topic}:{message}"
        self.socket.send_string(full_msg)

class ZMQPublisher:
    def __init__(self, bind_addr="tcp://localhost:7556"):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.bind(bind_addr)

        self._queue = queue.Queue()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._send_loop, daemon=True)
        self._thread.start()

    def send(self, topic: str, message: str):
        """非同期送信用キューに追加"""
        self._queue.put((topic, message))

    def _send_loop(self):
        while not self._stop_event.is_set():
            try:
                topic, message = self._queue.get(timeout=0.1)
                full_msg = f"{topic}:{message}"
                self.socket.send_string(full_msg)
            except queue.Empty:
                continue

    def close(self):
        """安全にスレッドとソケットを終了"""
        self._stop_event.set()
        self._thread.join(timeout=1)
        self.socket.close()
        self.context.term()

class ZMQSubscriber:
    def __init__(self, connect_addr="tcp://localhost:7556", topic_filter=""):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.SUB)
        self.socket.connect(connect_addr)

        if isinstance(topic_filter, (list, tuple, set)):
            for flt in topic_filter:
                self.socket.setsockopt_string(zmq.SUBSCRIBE, flt)
        else:
            self.socket.setsockopt_string(zmq.SUBSCRIBE, topic_filter)

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
                    msg = self.socket.recv_string()
                    if self._callback:
                        self._callback(msg)
        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
        self.socket.close()
        self.context.term()
