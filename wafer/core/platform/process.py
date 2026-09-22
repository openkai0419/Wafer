import os
import subprocess
import sys
import threading
import psutil
from ..logs import AppLogger

MAIN_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "main.py")

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001

_kill_with_parent_job = None
_kill_with_parent_lock = threading.Lock()
_kill_with_parent_failed = False


def _windows_no_window_flags(extra=0):
    if sys.platform != "win32":
        return 0
    flags = extra
    flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return flags


def _build_kill_on_close_job():
    import ctypes
    from ctypes import wintypes

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ("Read", "Write", "Other", "ReadBytes", "WriteBytes", "OtherBytes")]

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimits),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), ctypes.sizeof(limits)):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(job)
        raise OSError(error, "SetInformationJobObject failed")
    return kernel32, job


def kill_with_parent(pid: int) -> bool:
    """Tie an external child process to this process: Windows kills it when we exit, however we exit.

    Use for third-party binaries (exiftool, ffmpeg, ...). Never for Wafer's own processes,
    which are spawned detached on purpose and must outlive their parent.
    """
    global _kill_with_parent_job, _kill_with_parent_failed
    if sys.platform != "win32" or _kill_with_parent_failed:
        return False
    import ctypes
    from ctypes import wintypes

    with _kill_with_parent_lock:
        if _kill_with_parent_job is None:
            try:
                _kill_with_parent_job = _build_kill_on_close_job()
            except OSError as e:
                _kill_with_parent_failed = True
                AppLogger.warning("kill_with_parent: job object unavailable, children may outlive this process", exc=e)
                return False
        kernel32, job = _kill_with_parent_job

    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    handle = kernel32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
    if not handle:
        AppLogger.warning(f"kill_with_parent: cannot open pid={pid} (error={ctypes.get_last_error()})")
        return False
    try:
        if not kernel32.AssignProcessToJobObject(job, handle):
            AppLogger.warning(f"kill_with_parent: cannot assign pid={pid} (error={ctypes.get_last_error()})")
            return False
    finally:
        kernel32.CloseHandle(handle)
    return True


class ProcessMatcher:
    def __init__(self, cmd_list):
        if not cmd_list:
            raise ValueError("cmd_list must not be empty")
        self._raw_cmd = list(cmd_list)
        self.exe_path = self._normalize_path(cmd_list[0])
        self.script_path = self._normalize_path(cmd_list[1]) if len(cmd_list) > 1 else None
        self.args_set = set(cmd_list[2:])

    def find_by_args_subset(self, exclude_args=None):
        return list(self._iter_matches(compare="subset", exclude_args=exclude_args))

    def find_by_args_exact(self):
        return list(self._iter_matches(compare="equal"))

    def start_if_not_running(self, **popen_kwargs):
        existing = self.find_by_args_exact()
        if existing:
            return (False, existing)
        if sys.platform == "win32":
            flags = popen_kwargs.pop("creationflags", 0)
            popen_kwargs["creationflags"] = _windows_no_window_flags(flags)
        new_popen = subprocess.Popen(self._raw_cmd, **popen_kwargs)
        try:
            proc = psutil.Process(new_popen.pid)
        except psutil.NoSuchProcess:
            return (True, [])
        return (True, [proc])

    def _iter_matches(self, compare, exclude_args=None):
        for p in psutil.process_iter(["pid", "cmdline"]):
            try:
                pcmd = p.info.get("cmdline") or []
                if not pcmd:
                    continue
                if not self._same_executable(pcmd[0], self.exe_path):
                    continue
                if self.script_path is not None:
                    if len(pcmd) < 2 or not self._same_executable(pcmd[1], self.script_path):
                        continue
                    proc_args_set = set(pcmd[2:])
                else:
                    proc_args_set = set(pcmd[1:])
                if exclude_args and not exclude_args.isdisjoint(proc_args_set):
                    continue
                if compare == "subset":
                    if self.args_set.issubset(proc_args_set):
                        yield p
                elif compare == "equal":
                    if self.args_set == proc_args_set:
                        yield p
                else:
                    raise ValueError(f"unknown compare mode: {compare}")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    @staticmethod
    def _normalize_path(path):
        norm = os.path.normpath(os.path.realpath(path))
        return os.path.normcase(norm) if os.name == "nt" else norm

    @staticmethod
    def _same_executable(pcmd0, expected_normpath):
        if ProcessMatcher._normalize_path(pcmd0) == expected_normpath:
            return True
        try:
            return os.path.samefile(pcmd0, expected_normpath)
        except (FileNotFoundError, PermissionError, OSError):
            return False


class AppProcess:
    WORKER_FLAGS = frozenset({"--tray", "--indexer", "--collector", "--parser", "--webui"})

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
    def terminate_cmd(cls, *args, compare="subset", wait=False, timeout=5, kill_timeout=3, recursive=False, exclude_self=False):
        matcher = ProcessMatcher(cls.base_command() + list(args))
        procs = matcher.find_by_args_subset() if compare == "subset" else matcher.find_by_args_exact()
        if exclude_self:
            procs = [p for p in procs if p.pid != os.getpid()]
        AppLogger.info(f"terminate_cmd: {len(procs)} processes found (wait={wait})")
        if recursive:
            cls.terminate_tree(procs, timeout=timeout, kill_timeout=kill_timeout)
        elif wait:
            cls.terminate_and_wait(procs, timeout=timeout, kill_timeout=kill_timeout)
        else:
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
        if not processes:
            return
        AppProcess.terminate(processes)
        AppProcess.wait_procs_then_kill(processes, wait=timeout, kill_timeout=kill_timeout)

    @staticmethod
    def collect_process_tree(processes):
        by_pid = {}
        for process in processes:
            try:
                by_pid[process.pid] = process
                for child in process.children(recursive=True):
                    by_pid[child.pid] = child
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return list(by_pid.values())

    @classmethod
    def terminate_tree(cls, processes, timeout=5, kill_timeout=3):
        tree = cls.collect_process_tree(processes)
        if not tree:
            return
        cls.terminate_and_wait(tree, timeout=timeout, kill_timeout=kill_timeout)

    @staticmethod
    def shutdown_children(timeout=5, kill_timeout=3):
        children = AppProcess.children(recursive=True)
        if not children:
            return
        AppLogger.info(f"shutdown_children: terminating {len(children)} child processes")
        AppProcess.terminate_and_wait(children, timeout, kill_timeout)

    @classmethod
    def list_app(cls, *args, exclude_self=True):
        procs = ProcessMatcher(cls.base_command() + list(args)).find_by_args_subset()
        if exclude_self:
            me = os.getpid()
            procs = [p for p in procs if p.pid != me]
        return procs

    @classmethod
    def list_viewers(cls, exclude_self=True):
        procs = ProcessMatcher(cls.base_command()).find_by_args_subset(exclude_args=cls.WORKER_FLAGS)
        if exclude_self:
            me = os.getpid()
            procs = [p for p in procs if p.pid != me]
        return procs

    @staticmethod
    def wait_procs_then_kill(processes, wait=5, kill_timeout=3):
        if not processes:
            return
        _, alive = psutil.wait_procs(processes, timeout=wait)
        for p in alive:
            try:
                p.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if alive:
            AppLogger.info(f"wait_procs_then_kill: force-killed {len(alive)} unresponsive processes")
            psutil.wait_procs(alive, timeout=kill_timeout)

    @classmethod
    def force_close_all(cls, timeout=5, kill_timeout=3):
        procs = cls.list_app(exclude_self=True)
        AppLogger.info(f"force_close_all: terminating {len(procs)} app processes")
        cls.terminate_and_wait(procs, timeout=timeout, kill_timeout=kill_timeout)
        return len(procs)

    @classmethod
    def ensure_tray(cls):
        if cls.get_by_args_subset("--tray"):
            return False
        cls.new_main("--tray")
        return True

    @staticmethod
    def _in_venv():
        return sys.prefix != getattr(sys, "base_prefix", sys.prefix)

    @staticmethod
    def base_command():
        exe = sys.executable
        base_exe = getattr(sys, "_base_executable", None)
        if base_exe and AppProcess._in_venv() and os.path.normcase(base_exe) != os.path.normcase(exe):
            exe = base_exe
        return [exe, MAIN_SCRIPT]

    @staticmethod
    def new_main(*args, extra_env=None, **popen_kwargs):
        cmd = AppProcess.base_command() + list(args)
        env = os.environ.copy()
        if AppProcess._in_venv():
            env["__PYVENV_LAUNCHER__"] = sys.executable
        if extra_env:
            env.update(extra_env)
        popen_kwargs.setdefault("stdin", subprocess.DEVNULL)
        popen_kwargs.setdefault("stdout", subprocess.DEVNULL)
        popen_kwargs.setdefault("stderr", subprocess.DEVNULL)
        if sys.platform == "win32":
            flags = popen_kwargs.pop("creationflags", 0)
            flags |= getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            flags = _windows_no_window_flags(flags)
            popen_kwargs["creationflags"] = flags
            popen_kwargs.setdefault("close_fds", True)
        proc = subprocess.Popen(cmd, env=env, **popen_kwargs)
        AppLogger.info(f"new_main: spawned pid={proc.pid} args={list(args)}")
        return proc


def run_external(cmd, timeout=None, capture_output=False, check=False, **popen_kwargs) -> subprocess.CompletedProcess:
    """subprocess.run for third-party binaries: no console window, tied to this process, tree killed on timeout."""
    if capture_output:
        popen_kwargs["stdout"] = subprocess.PIPE
        popen_kwargs["stderr"] = subprocess.PIPE
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = _windows_no_window_flags(popen_kwargs.pop("creationflags", 0))
    with subprocess.Popen(cmd, **popen_kwargs) as proc:
        kill_with_parent(proc.pid)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            AppLogger.warning(f"run_external: timed out after {timeout}s, killing {cmd[0]}")
            terminate_pid_tree(proc.pid)
            stdout, stderr = proc.communicate()
            raise subprocess.TimeoutExpired(cmd, timeout, output=stdout, stderr=stderr) from None
        result = subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
        if check:
            result.check_returncode()
        return result


def terminate_pid_tree(pid: int, timeout=1, kill_timeout=2):
    """Kill an external child and everything it spawned. Dropping a live child's reference leaks it forever."""
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    AppProcess.terminate_tree([proc], timeout=timeout, kill_timeout=kill_timeout)
