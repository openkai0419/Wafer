import zmq
import threading

class ZMQPublisher:
    def __init__(self, bind_addr="tcp://*:7556"):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.bind(bind_addr)

    def send(self, topic: str, message: str):
        full_msg = f"{topic}:{message}"
        self.socket.send_string(full_msg)

class ZMQSubscriber:
    def __init__(self, connect_addr="tcp://localhost:7556", topic_filter=""):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.SUB)
        self.socket.connect(connect_addr)
        self.socket.setsockopt_string(zmq.SUBSCRIBE, topic_filter)
        self._callback = None

    def connect_on_message(self, callback):
        self._callback = callback

    def start(self):
        def loop():
            while True:
                msg = self.socket.recv_string()
                if self._callback:
                    self._callback(msg)
        threading.Thread(target=loop, daemon=True).start()