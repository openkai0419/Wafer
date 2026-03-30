import os
import subprocess
import sys
import psutil
from ...utils.logs import AppLogger
class ProcessMatcher:

    def __init__(self, cmd_list):
        if not cmd_list:
            raise ValueError('cmd_list must not be empty')
        self._raw_cmd = list(cmd_list)
        self.exe_path = self._normalize_path(cmd_list[0])
        self.args_set = set(cmd_list[1:])

    def find_by_args_subset(self):
        return list(self._iter_matches(compare='subset'))

    def find_by_args_exact(self):
        return list(self._iter_matches(compare='equal'))

    def start_if_not_running(self, **popen_kwargs):
        existing = self.find_by_args_exact()
        if existing:
            return (False, existing)
        new_popen = subprocess.Popen(self._raw_cmd, **popen_kwargs)
        try:
            proc = psutil.Process(new_popen.pid)
        except psutil.NoSuchProcess:
            return (True, [])
        return (True, [proc])

    def _iter_matches(self, compare):
        for p in psutil.process_iter(['pid', 'cmdline']):
            try:
                pcmd = p.info.get('cmdline') or []
                if not pcmd:
                    continue
                if not self._same_executable(pcmd[0], self.exe_path):
                    continue
                proc_args_set = set(pcmd[1:])
                if compare == 'subset':
                    if self.args_set.issubset(proc_args_set):
                        yield p
                elif compare == 'equal':
                    if self.args_set == proc_args_set:
                        yield p
                else:
                    raise ValueError(f'unknown compare mode: {compare}')
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    @staticmethod
    def _normalize_path(path):
        norm = os.path.normpath(os.path.realpath(path))
        return os.path.normcase(norm) if os.name == 'nt' else norm

    @staticmethod
    def _same_executable(pcmd0, expected_normpath):
        pcmd_norm = ProcessMatcher._normalize_path(pcmd0)
        if pcmd_norm == expected_normpath:
            return True
        try:
            if os.path.samefile(pcmd0, expected_normpath):
                return True
        except (FileNotFoundError, PermissionError, OSError):
            pass
        base = getattr(sys, '_base_executable', None)
        if base:
            equiv = {
                ProcessMatcher._normalize_path(sys.executable),
                ProcessMatcher._normalize_path(base),
            }
            if pcmd_norm in equiv and expected_normpath in equiv:
                return True
        return False

class AppProcess:

    @classmethod
    def get_by_args_exact(cls, *args):
        return ProcessMatcher(cls.base_command() + list(args)).find_by_args_exact()

    @classmethod
    def get_by_args_subset(cls, *args):
        return ProcessMatcher(cls.base_command() + list(args)).find_by_args_subset()

    @classmethod
    def start_if_not_running(cls, *args, **popen_kwargs):
        return ProcessMatcher(cls.base_command() + list(args)).start_if_not_running(**popen_kwargs)

    @classmethod
    def terminate_cmd(cls, *args, compare='subset'):
        matcher = ProcessMatcher(cls.base_command() + list(args))
        procs = matcher.find_by_args_subset() if compare == 'subset' else matcher.find_by_args_exact()
        AppLogger.info(f'terminate_cmd: {len(procs)} processes found')
        cls.terminate(procs)
        return len(procs)

    @staticmethod
    def children(recursive=False):
        try:
            return psutil.Process().children(recursive=recursive)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return []

    @staticmethod
    def terminate(processes):
        for process in processes:
            try:
                process.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    @staticmethod
    def terminate_and_wait(processes, timeout=5, kill_timeout=3):
        for p in processes:
            try:
                p.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        _, alive = psutil.wait_procs(processes, timeout=timeout)
        for p in alive:
            try:
                p.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        psutil.wait_procs(alive, timeout=kill_timeout)

    @staticmethod
    def shutdown_children(timeout=5, kill_timeout=3):
        children = AppProcess.children(recursive=True)
        if not children:
            return
        AppLogger.info(f'shutdown_children: terminating {len(children)} child processes')
        AppProcess.terminate_and_wait(children, timeout, kill_timeout)

    @staticmethod
    def base_command():
        if getattr(sys, 'frozen', False):
            return [sys.executable]
        else:
            main_path = os.path.abspath(sys.argv[0])
            return [sys.executable, main_path]

    @staticmethod
    def new_main(*args, **popen_kwargs):
        cmd = AppProcess.base_command() + list(args)
        env = os.environ.copy()
        popen_kwargs.setdefault('stdin', subprocess.DEVNULL)
        popen_kwargs.setdefault('stdout', subprocess.DEVNULL)
        popen_kwargs.setdefault('stderr', subprocess.DEVNULL)
        return subprocess.Popen(cmd, env=env, **popen_kwargs)
