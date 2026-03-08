from .signal import Signal


class Notifier:
    on_info = Signal()
    on_warning = Signal()
    on_error = Signal()

    @staticmethod
    def info(text: str) -> None:
        Notifier.on_info.emit(text)

    @staticmethod
    def warning(text: str) -> None:
        Notifier.on_warning.emit(text)

    @staticmethod
    def error(text: str) -> None:
        Notifier.on_error.emit(text)
