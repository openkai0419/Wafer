from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import psutil


ROLE_FLAGS = ("tray", "viewer", "webui", "indexer", "collector", "parser")
MB = 1024 * 1024


def role_of(cmdline: list[str]) -> str | None:
    main_index = next((i for i, arg in enumerate(cmdline) if Path(arg).name == "main.py"), None)
    if main_index is None:
        return None
    flags = {arg[2:] for arg in cmdline[main_index + 1 :] if arg.startswith("--")}
    return next((role for role in ROLE_FLAGS if role in flags), "root-viewer")


def collect() -> dict[str, list[int]]:
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0, 0])
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            role = role_of(proc.info["cmdline"] or [])
            if role is None:
                continue
            memory = proc.memory_full_info()
            threads = proc.num_threads()
        except psutil.Error as e:
            print(f"skipped pid {proc.pid}: {e}")
            continue
        row = totals[role]
        for i, value in enumerate((memory.rss, memory.uss, memory.private, threads, 1)):
            row[i] += value
    return totals


def format_row(label: str, ws: int, uss: int, commit: int, threads: int, count: int) -> str:
    return f"{label:<14}{count:>6}{ws / MB:>10.1f}{uss / MB:>10.1f}{commit / MB:>11.1f}{threads:>9}"


def format_report(totals: dict[str, list[int]]) -> str:
    lines = [f"{'role':<14}{'count':>6}{'WS MB':>10}{'USS MB':>10}{'commit MB':>11}{'threads':>9}"]
    lines += [format_row(role, *totals[role]) for role in sorted(totals)]
    lines.append(format_row("total", *(sum(column) for column in zip(*totals.values())) if totals else (0,) * 5))
    return "\n".join(lines)


def main() -> int:
    print(format_report(collect()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
