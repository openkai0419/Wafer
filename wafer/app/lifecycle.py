from enum import Enum, auto


class CloseReason(Enum):
    NORMAL = auto()
    SLOT_DELETE = auto()
    RESTART = auto()
    SHUTDOWN = auto()
