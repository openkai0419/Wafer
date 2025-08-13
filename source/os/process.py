import os
import subprocess
import sys

import psutil

from ..common.profiling import logger


class ProcessMatcher:
    def __init__(self, cmd_list):
        if not cmd_list:
            raise ValueError("cmd_listは空にできません")
        self._raw_cmd = list(cmd_list)
        self.exe_path = self._normalize_path(cmd_list[0])
        self.args_set = set(cmd_list[1:])

    def find_subset(self):
        return list(self._iter_matches(compare="subset"))

    def find_exact(self):
        return list(self._iter_matches(compare="equal"))

    def start_if_not(self, **popen_kwargs):
        existing = self.find_exact()
        if existing:
            return False, existing
        new_popen = subprocess.Popen(self._raw_cmd, **popen_kwargs)
        try:
            proc = psutil.Process(new_popen.pid)
        except psutil.NoSuchProcess:
            return True, []
        return True, [proc]

    def _iter_matches(self, compare):
        for p in psutil.process_iter(["pid", "cmdline"]):
            try:
                pcmd = p.info.get("cmdline") or []
                if not pcmd:
                    continue
                if not self._same_executable(pcmd[0], self.exe_path):
                    continue
                proc_args_set = set(pcmd[1:])
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
        try:
            return os.path.samefile(pcmd0, expected_normpath)
        except (FileNotFoundError, PermissionError, OSError):
            pcmd_norm = ProcessMatcher._normalize_path(pcmd0)
            return pcmd_norm == expected_normpath


class Proc:
    @classmethod
    def get_exact(cls, *args):
        return ProcessMatcher(cls.cmd() + list(args)).find_exact()

    @classmethod
    def get_subset(cls, *args):
        return ProcessMatcher(cls.cmd() + list(args)).find_subset()

    @classmethod
    def start_if_not(cls, *args, **popen_kwargs):
        return ProcessMatcher(cls.cmd() + list(args)).start_if_not(**popen_kwargs)

    @classmethod
    def terminate_cmd(cls, *args, compare="subset"):
        matcher = ProcessMatcher(cls.cmd() + list(args))
        procs = matcher.find_subset() if compare == "subset" else matcher.find_exact()
        logger.info(procs)
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
    def cmd():
        if getattr(sys, "frozen", False):
            return [sys.executable]
        else:
            main_path = os.path.abspath(sys.argv[0])
            return [sys.executable, main_path]

    @staticmethod
    def new_main(*args, **popen_kwargs):
        cmd = Proc.cmd() + list(args)
        env = os.environ.copy()
        return subprocess.Popen(cmd, env=env, **popen_kwargs)
