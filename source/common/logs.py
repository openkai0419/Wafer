from __future__ import annotations

import glob
import logging
import logging.handlers
import os
import re
import sys

import psutil

import traceback

from .funcs import data_path
from .signal import Signal

_LOG_PATH = data_path('.log')
_logger = None
_initialized = False
_role = ''


def _is_pid_active(pid):
    return psutil.pid_exists(pid)


def _cleanup_old_logs(log_dir=_LOG_PATH, keep_latest=10):
    try:
        log_files = sorted(
            glob.glob(os.path.join(log_dir, '*.log*')),
            key=os.path.getmtime, reverse=True,
        )
        deleted = 0
        primary_files = [f for f in log_files if re.match(r'.*\.log$', f)]
        for f in log_files:
            base = re.sub(r'\.log(?:\.\d+)?$', '.log', f)
            if base not in primary_files[:keep_latest]:
                match = re.search(r'\w+?_(\d+)\.log', os.path.basename(base))
                if match:
                    pid = int(match.group(1))
                    if _is_pid_active(pid):
                        continue
                try:
                    os.remove(f)
                    deleted += 1
                except Exception as e:
                    print(f'Failed to delete {f}: {e}')
        return deleted
    except Exception as e:
        print(f'_cleanup_old_logs failed: {e}', file=sys.stderr)
        return 0


def _make_log_id(role: str = '') -> str:
    pid = os.getpid()
    return f'{role}_{pid}' if role else str(pid)


class _LoggerFactory:
    _instance = None
    _file_handler = None

    @classmethod
    def get(cls, role: str = ''):
        log_id = _make_log_id(role)
        if cls._instance is not None and cls._file_handler is None:
            os.makedirs(_LOG_PATH, exist_ok=True)
            log_filename = os.path.join(_LOG_PATH, f'{log_id}.log')
            fh = logging.handlers.RotatingFileHandler(
                log_filename, maxBytes=100000, backupCount=5,
                encoding='utf-8', delay=True,
            )
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
            cls._instance.addHandler(fh)
            cls._file_handler = fh
            return cls._instance
        if cls._instance is not None:
            return cls._instance
        logger = logging.getLogger(f'AppLog-{log_id}')
        logger.setLevel(logging.DEBUG)
        if not logger.hasHandlers():
            stream_handler = logging.StreamHandler()
            stream_handler.setLevel(logging.DEBUG)
            stream_handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
            logger.addHandler(stream_handler)
        cls._instance = logger
        return logger


class AppLogger:
    on_critical = Signal()
    on_error = Signal()
    on_warning = Signal()
    on_info = Signal()
    on_debug = Signal()
    _node = None
    _role = ''

    @staticmethod
    def set_role(role: str):
        global _logger, _role
        _role = role
        AppLogger._role = role
        _logger = _LoggerFactory.get(role)

    @staticmethod
    def set_node(node, role: str = ''):
        AppLogger._node = node
        if role:
            AppLogger.set_role(role)

    @staticmethod
    def _forward(level: str, text: str):
        node = AppLogger._node
        if node is None:
            return
        try:
            node.send('dev.log', {
                'level': level,
                'text': text,
            }, dst='viewer', priority=2)
        except Exception:
            pass

    @staticmethod
    def _format_with_exc(text: str, exc: BaseException | None) -> str:
        if exc is None:
            return text
        tb = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        return f'{text}\n{tb.rstrip()}'

    @staticmethod
    def error(text: str, *, exc: BaseException | None = None) -> None:
        if _logger is not None:
            _logger.error(text, exc_info=exc)
        full = AppLogger._format_with_exc(text, exc)
        AppLogger.on_error.emit(full)
        AppLogger._forward('error', full)

    @staticmethod
    def warning(text: str, *, exc: BaseException | None = None) -> None:
        if _logger is not None:
            _logger.warning(text, exc_info=exc)
        full = AppLogger._format_with_exc(text, exc)
        AppLogger.on_warning.emit(full)
        AppLogger._forward('warning', full)

    @staticmethod
    def info(text: str) -> None:
        if _logger is not None:
            _logger.info(text)
        AppLogger.on_info.emit(text)
        AppLogger._forward('info', text)

    @staticmethod
    def debug(text: str) -> None:
        if _logger is not None:
            _logger.debug(text)
        AppLogger.on_debug.emit(text)
        AppLogger._forward('debug', text)


def _create_exception_hook():
    def exception_hook(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        if _logger is not None:
            _logger.critical(
                'Uncaught exception',
                exc_info=(exc_type, exc_value, exc_traceback),
            )
        AppLogger.on_critical.emit('Uncaught exception')
        try:
            from PySide6 import QtWidgets
            if QtWidgets.QApplication.instance():
                QtWidgets.QMessageBox.critical(
                    None, 'Unexpected Error',
                    'An unexpected error occurred. Please check the log file.',
                )
        except Exception as e:
            print(f'Failed to show error dialog: {e}', file=sys.stderr)
        sys.exit(1)
    return exception_hook


def _initialize():
    global _logger, _initialized
    if _initialized:
        return
    _logger = _LoggerFactory.get()
    sys.excepthook = _create_exception_hook()
    _cleanup_old_logs(keep_latest=0)
    _initialized = True


_initialize()
