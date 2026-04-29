from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
SUMMARY_PATH = ROOT / "tests" / "test_summary.txt"
LOG_DIR = ROOT / ".temp" / "test_logs"

LAYERS: dict[str, dict] = {
    "unit": {
        "paths": ["tests-unit/"],
        "label": "Layer 1: Unit Tests",
        "maxfail": 20,
    },
    "smoke": {
        "paths": ["tests/smoke/", "tests/integration/"],
        "label": "Layer 2: Smoke / Integration",
        "maxfail": 10,
    },
    "benchmark": {
        "paths": ["tests/benchmark/"],
        "label": "Layer 3: Benchmark",
        "maxfail": 5,
        "extra_args": ["-m", "benchmark", "--timeout=0"],
        "timeout": 3600,
    },
    "setup": {
        "paths": ["tests/smoke/test_extension_install.py", "tests/smoke/test_extension_verify.py"],
        "label": "Layer 4: Extension Setup",
        "maxfail": 5,
        "extra_args": ["-m", "setup", "--run-setup"],
        "timeout": 7800,
    },
}

DEFAULT_LAYERS = ["unit", "smoke"]

_TRACEBACK_SEP = re.compile(r"^_{10,}$")
_TRACEBACK_HEAD = re.compile(r"^Traceback \(most recent call last\):")


@dataclass
class LayerResult:
    name: str
    label: str
    exit_code: int | None = None
    crashed: bool = False
    skipped: bool = False
    duration: float = 0.0
    summary_text: str = ""
    counts: dict[str, int] = field(default_factory=lambda: {"passed": 0, "failed": 0, "skipped": 0, "error": 0})
    categories: dict[str, dict[str, int]] = field(default_factory=dict)
    failed_nodes: list[str] = field(default_factory=list)
    error_nodes: list[str] = field(default_factory=list)


def parse_summary(path: Path) -> dict:
    result: dict = {"counts": {}, "categories": {}, "failed": [], "errors": [], "raw": ""}
    if not path.exists():
        return result
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return result
    result["raw"] = text
    section = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("passed:"):
            result["counts"]["passed"] = int(stripped.split(":")[1].strip())
        elif stripped.startswith("failed:"):
            result["counts"]["failed"] = int(stripped.split(":")[1].strip())
        elif stripped.startswith("skipped:"):
            result["counts"]["skipped"] = int(stripped.split(":")[1].strip())
        elif stripped.startswith("error:"):
            result["counts"]["error"] = int(stripped.split(":")[1].strip())
        elif stripped == "--- BY CATEGORY ---":
            section = "category"
        elif stripped == "--- FAILED ---":
            section = "failed"
        elif stripped == "--- ERROR ---":
            section = "error"
        elif section == "failed" and stripped:
            if line.startswith("    "):
                continue
            result["failed"].append(stripped)
        elif section == "error" and stripped:
            if line.startswith("    "):
                continue
            result["errors"].append(stripped)
        elif section == "category" and stripped:
            parts = stripped.split(":", 1)
            if len(parts) == 2:
                result["categories"][parts[0].strip()] = parts[1].strip()
    return result


def _dedup_stderr(stderr: str, max_unique: int = 5) -> str:
    blocks: list[str] = []
    current: list[str] = []
    in_block = False

    for line in stderr.splitlines():
        if _TRACEBACK_SEP.match(line):
            if in_block and current:
                blocks.append("\n".join(current))
                current = []
            in_block = not in_block
            continue
        if _TRACEBACK_HEAD.match(line):
            if current:
                blocks.append("\n".join(current))
            current = [line]
            in_block = True
            continue
        if in_block:
            current.append(line)
        else:
            if current:
                blocks.append("\n".join(current))
                current = []

    if current:
        blocks.append("\n".join(current))

    counts: Counter[str] = Counter()
    seen_order: list[str] = []
    for b in blocks:
        key = b.strip()
        if key not in counts:
            seen_order.append(key)
        counts[key] += 1

    lines: list[str] = []
    for key in seen_order[:max_unique]:
        c = counts[key]
        if c > 1:
            lines.append(f"[repeated {c}x]\n{key}")
        else:
            lines.append(key)

    omitted = len(seen_order) - max_unique
    if omitted > 0:
        lines.append(f"  ... and {omitted} more unique stderr blocks omitted")

    return "\n".join(lines)


def _print_progress(stdout: str):
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("FAILED", "ERROR", "===")) or all(c in ".FEsxX \t" for c in stripped.split("[")[0].rstrip()) or "passed" in stripped or "failed" in stripped or "error" in stripped:
            print(line)


def run_layer(name: str, cfg: dict, extra_pytest_args: list[str] | None = None) -> LayerResult:
    result = LayerResult(name=name, label=cfg["label"])
    temp_dir = ROOT / ".temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    summary_path = temp_dir / f"_summary_{name}_{os.getpid()}.txt"
    if summary_path.exists():
        summary_path.unlink()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_stdout = LOG_DIR / f"{name}_stdout.log"
    log_stderr = LOG_DIR / f"{name}_stderr.log"

    env = os.environ.copy()
    env["WAFER_TEST_SUMMARY_PATH"] = str(summary_path)

    cmd = [
        str(VENV_PYTHON),
        "-m",
        "pytest",
        *cfg["paths"],
        "-p",
        "no:cacheprovider",
        "-q",
        f"--maxfail={cfg['maxfail']}",
    ]
    if "extra_args" in cfg:
        cmd.extend(cfg["extra_args"])
    if extra_pytest_args:
        cmd.extend(extra_pytest_args)

    print(f"\n{'=' * 60}")
    print(f"  {cfg['label']}")
    print(f"  paths: {', '.join(cfg['paths'])}")
    print(f"{'=' * 60}\n")

    t0 = time.time()
    layer_timeout = cfg.get("timeout", 600)
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            env=env,
            timeout=layer_timeout,
            capture_output=True,
            text=True,
            errors="replace",
        )
        result.exit_code = proc.returncode

        log_stdout.write_text(proc.stdout, encoding="utf-8")
        log_stderr.write_text(proc.stderr, encoding="utf-8")

        _print_progress(proc.stdout)

        if proc.stderr.strip():
            deduped = _dedup_stderr(proc.stderr)
            if deduped.strip():
                print(f"\n  --- stderr (deduped, full: {log_stderr.name}) ---")
                for line in deduped.splitlines()[:30]:
                    print(f"  {line}")
                if deduped.count("\n") > 30:
                    print(f"  ... truncated (see {log_stderr})")
                print()

    except subprocess.TimeoutExpired as e:
        print(f"\n  !! {name} TIMED OUT ({layer_timeout}s limit) !!")
        result.exit_code = -1
        result.crashed = True
        if e.stdout:
            log_stdout.write_text(e.stdout if isinstance(e.stdout, str) else e.stdout.decode("utf-8", errors="replace"), encoding="utf-8")
        if e.stderr:
            log_stderr.write_text(e.stderr if isinstance(e.stderr, str) else e.stderr.decode("utf-8", errors="replace"), encoding="utf-8")
    except Exception as exc:
        print(f"\n  !! {name} LAUNCH FAILED: {exc} !!")
        result.exit_code = -1
        result.crashed = True
    finally:
        result.duration = time.time() - t0

        if summary_path.exists() and summary_path.stat().st_size > 0:
            parsed = parse_summary(summary_path)
            result.counts = parsed.get("counts", result.counts)
            result.categories = parsed.get("categories", {})
            result.failed_nodes = parsed.get("failed", [])
            result.error_nodes = parsed.get("errors", [])
            result.summary_text = parsed.get("raw", "")
        elif result.exit_code and result.exit_code != 0:
            result.crashed = True

        total = sum(result.counts.values())
        if result.exit_code and result.exit_code != 0 and total == 0 and not result.crashed:
            result.crashed = True

        try:
            summary_path.unlink(missing_ok=True)
        except OSError:
            pass

    return result


def write_combined_summary(results: list[LayerResult], total_elapsed: float):
    total_counts = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
    all_categories: dict[str, str] = {}
    all_failed: list[str] = []
    all_errors: list[str] = []
    crashed_layers: list[str] = []

    for r in results:
        if r.skipped:
            continue
        for k in total_counts:
            total_counts[k] += r.counts.get(k, 0)
        all_categories.update(r.categories)
        all_failed.extend(r.failed_nodes)
        all_errors.extend(r.error_nodes)
        if r.crashed:
            crashed_layers.append(r.name)

    total = sum(total_counts.values())
    minutes, seconds = divmod(total_elapsed, 60)

    has_failure = total_counts["failed"] > 0 or total_counts["error"] > 0 or crashed_layers
    exit_status = 1 if has_failure else 0

    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        f.write(f"total: {total}\n")
        f.write(f"passed: {total_counts['passed']}\n")
        f.write(f"failed: {total_counts['failed']}\n")
        f.write(f"skipped: {total_counts['skipped']}\n")
        f.write(f"error: {total_counts['error']}\n")
        f.write(f"exitstatus: {exit_status}\n")
        f.write(f"duration: {int(minutes)}m {seconds:.1f}s\n")

        f.write("\n--- LAYER SUMMARY ---\n")
        for r in results:
            if r.skipped:
                f.write(f"  {r.label}: SKIPPED\n")
                continue
            m, s = divmod(r.duration, 60)
            status = "CRASH" if r.crashed else ("FAIL" if r.counts.get("failed", 0) or r.counts.get("error", 0) else "OK")
            c = r.counts
            f.write(f"  {r.label}: {status} ({c.get('passed', 0)} passed, {c.get('failed', 0)} failed, {c.get('error', 0)} error) [{int(m)}m {s:.1f}s]\n")

        if all_categories:
            f.write("\n--- BY CATEGORY ---\n")
            for cat in sorted(all_categories):
                f.write(f"  {cat}: {all_categories[cat]}\n")

        if crashed_layers:
            f.write("\n--- CRASHED LAYERS ---\n")
            for name in crashed_layers:
                f.write(f"  {name}: process crashed or produced no summary\n")

        if all_failed:
            f.write("\n--- FAILED ---\n")
            for line in all_failed:
                f.write(f"  {line}\n")

        if all_errors:
            f.write("\n--- ERROR ---\n")
            for line in all_errors:
                f.write(f"  {line}\n")


def print_final_report(results: list[LayerResult], total_elapsed: float):
    total_counts = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
    crashed = []

    for r in results:
        if r.skipped:
            continue
        for k in total_counts:
            total_counts[k] += r.counts.get(k, 0)
        if r.crashed:
            crashed.append(r.name)

    m, s = divmod(total_elapsed, 60)

    print(f"\n{'=' * 60}")
    print(f"  FINAL REPORT  ({int(m)}m {s:.1f}s)")
    print(f"{'=' * 60}")
    for r in results:
        if r.skipped:
            print(f"  {r.label}: SKIPPED")
            continue
        rm, rs = divmod(r.duration, 60)
        c = r.counts
        if r.crashed:
            status = "\033[91mCRASH\033[0m"
        elif c.get("failed", 0) or c.get("error", 0):
            status = "\033[91mFAIL\033[0m"
        else:
            status = "\033[92mOK\033[0m"
        print(f"  {r.label}: {status}  ({c.get('passed', 0)} passed, {c.get('failed', 0)} failed, {c.get('error', 0)} error) [{int(rm)}m {rs:.1f}s]")

    if crashed:
        print(f"\n  \033[91m!! CRASHED: {', '.join(crashed)}\033[0m")

    total_fail = total_counts["failed"] + total_counts["error"] + len(crashed)
    if total_fail == 0:
        print(f"\n  \033[92mAll {total_counts['passed']} tests passed.\033[0m")
    else:
        all_failed = []
        all_errors = []
        for r in results:
            all_failed.extend(r.failed_nodes)
            all_errors.extend(r.error_nodes)
        if all_failed:
            print(f"\n  --- FAILED ({len(all_failed)}) ---")
            for node in all_failed:
                print(f"  \033[91m  {node}\033[0m")
        if all_errors:
            print(f"\n  --- ERROR ({len(all_errors)}) ---")
            for node in all_errors:
                print(f"  \033[91m  {node}\033[0m")
        if crashed:
            for name in crashed:
                log = LOG_DIR / f"{name}_stdout.log"
                print(f"\n  Raw log: {log}")
        print(f"\n  \033[91m{total_fail} issue(s). See tests/test_summary.txt\033[0m")
    print()


def main():
    parser = argparse.ArgumentParser(description="Layered test runner with crash isolation")
    parser.add_argument(
        "layers",
        nargs="*",
        default=[],
        help="Layers to run: unit, smoke, benchmark, all (default: unit + smoke)",
    )
    parser.add_argument("-x", "--stop-on-layer-fail", action="store_true", help="Stop after first layer with failures")
    parser.add_argument("--maxfail", type=int, default=None, help="Override maxfail per layer")
    raw_args = sys.argv[1:]
    if "--" in raw_args:
        split_at = raw_args.index("--")
        runner_args = raw_args[:split_at]
        passthrough_args = raw_args[split_at + 1 :]
    else:
        runner_args = raw_args
        passthrough_args = []
    args, extra = parser.parse_known_args(runner_args)
    extra.extend(passthrough_args)

    layer_names = args.layers or DEFAULT_LAYERS
    if "all" in layer_names:
        layer_names = list(LAYERS.keys())

    results: list[LayerResult] = []
    t0 = time.time()
    stop = False

    for name in layer_names:
        if name not in LAYERS:
            print(f"Unknown layer: {name}. Available: {', '.join(LAYERS.keys())}")
            sys.exit(2)

        if stop:
            r = LayerResult(name=name, label=LAYERS[name]["label"])
            r.skipped = True
            results.append(r)
            continue

        cfg = dict(LAYERS[name])
        if args.maxfail is not None:
            cfg["maxfail"] = args.maxfail

        r = run_layer(name, cfg, extra_pytest_args=extra if extra else None)
        results.append(r)

        if args.stop_on_layer_fail and (r.crashed or r.counts.get("failed", 0) or r.counts.get("error", 0)):
            stop = True

    total_elapsed = time.time() - t0
    write_combined_summary(results, total_elapsed)
    print_final_report(results, total_elapsed)

    has_failure = any((not r.skipped and (r.crashed or r.counts.get("failed", 0) or r.counts.get("error", 0))) for r in results)
    sys.exit(1 if has_failure else 0)


if __name__ == "__main__":
    main()
