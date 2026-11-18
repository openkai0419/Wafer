import argparse
import ast
import glob
import hashlib
import os
import shutil
import sys
import time
from collections.abc import Callable
from pathlib import Path

from wafer.core.common.paths import (
    debug_profiles_dir,
    normalize_path,
    profile_config_root,
    profile_data_root,
    sample_root,
    scratch_root,
)
from wafer.core.common.profile import PROFILE_ARG, PROFILE_PREFIX, validate_profile_name
from wafer.core.db.db_utils import open_readonly
from wafer.core.db.setting_db import SettingDB
from wafer.core.ipc.node import Node
from wafer.core.logs import AppLogger
from wafer.core.platform.process import AppProcess
from wafer.core.platform.process_lock import file_lock

MAIN_PROFILE = f"{PROFILE_PREFIX}main"
TEMPLATE_BUILD_PROFILE = f"{PROFILE_PREFIX}template-build"
TEMPLATE_DIR_NAME = "_template"
TEMPLATE_STAGING_SUFFIX = ".partial"
TEMPLATE_EXCLUDED = frozenset({".temp", ".log", "ipc"})
TEMPLATE_INDEX_TIMEOUT = 1800.0
TEMPLATE_LOCK_TIMEOUT = TEMPLATE_INDEX_TIMEOUT + 300.0
SAMPLE_DB_NAME = "sample"
SAMPLE_IGNORED_FOLDERS = ("coco/train2017", "coco/unlabeled2017")
SAMPLE_IGNORED_PATTERN = "coco/*.zip"
SCRATCH_SOURCE = "coco/val2017"
SCRATCH_IMAGE_COUNT = 24
SCHEMA_FILES = ("wafer/core/db/file_db.py", "wafer/core/db/setting_db.py")
UNFINISHED_STATUSES = ("pending", "dispatched")
INDEX_SETTLE_SECONDS = 5.0
INDEX_POLL_SECONDS = 1.0
STOP_REGISTER_SECONDS = 5.0
STOP_POLL_SECONDS = 0.25

Progress = Callable[[str], None]


def _is_checkout(path: Path) -> bool:
    return (path / "main.py").is_file() and (path / "wafer").is_dir()


def _same_name(a: str, b: str) -> bool:
    return os.path.normcase(a) == os.path.normcase(b)


def _real(path: Path) -> Path:
    return Path(os.path.realpath(path))


def main_root_of(checkout: Path) -> Path:
    path = _real(checkout)
    if not _is_checkout(path):
        raise ValueError(f"Not a Wafer checkout (main.py and wafer/ are required): {checkout}")
    main = path
    if _same_name(path.parent.name, "worktrees") and _same_name(path.parent.parent.name, ".claude"):
        main = path.parent.parent.parent
        if not _is_checkout(main):
            raise ValueError(f"Worktree is not inside a Wafer checkout: {checkout}")
    if any(_is_checkout(parent) for parent in main.parents):
        raise ValueError(f"Only the main checkout or one of its .claude/worktrees/<task> can be used, not a nested one: {checkout}")
    return main


def profile_name_for(checkout: Path) -> str:
    path = _real(checkout)
    main = main_root_of(path)
    if _same_name(str(path), str(main)):
        return MAIN_PROFILE
    return validate_profile_name(f"{PROFILE_PREFIX}{path.name}")


def _create_statements(source: str) -> list[str]:
    nodes = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Constant) and isinstance(node.value, str) and "CREATE" in node.value]
    return [node.value for node in sorted(nodes, key=lambda node: (node.lineno, node.col_offset))]


def schema_hash(checkout: Path) -> str:
    statements = []
    for relative in SCHEMA_FILES:
        statements.extend(_create_statements((Path(checkout) / relative).read_text(encoding="utf-8")))
    return hashlib.sha256("".join(statements).encode("utf-8")).hexdigest()[:12]


def template_dir(digest: str) -> Path:
    return debug_profiles_dir() / TEMPLATE_DIR_NAME / digest


def _template_lock(digest: str) -> str:
    return str(debug_profiles_dir() / TEMPLATE_DIR_NAME / f"{digest}.lock")


def _sample_settings_db(root: Path) -> Path:
    return Path(root) / "dirs" / f"{SAMPLE_DB_NAME}.db"


def _sample_data_db(profile: str) -> Path:
    return profile_data_root(profile) / "data" / f"{SAMPLE_DB_NAME}.db"


def _add_parent_folder(settings: SettingDB, folder: Path) -> None:
    if not settings.add_parent_folder(str(folder)):
        raise RuntimeError(f"Could not register {folder} as a parent folder of {settings.db_name}")


def sample_db_setup(root: Path) -> None:
    db_path = _sample_settings_db(root)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    sample = sample_root()
    settings = SettingDB(str(db_path))
    _add_parent_folder(settings, sample)
    for folder in SAMPLE_IGNORED_FOLDERS:
        settings.add_ignore_folder(str(sample / folder))
    settings.add_ignore_pattern(f"{glob.escape(normalize_path(sample))}/{SAMPLE_IGNORED_PATTERN}")
    AppLogger.info(f"Sample DB settings written to {db_path} (sample root {sample})")


def _collected_source_count(db_path: Path) -> int:
    if not db_path.is_file():
        return 0
    conn = open_readonly(db_path)
    try:
        tables = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name IN ('sources', 'collection_status')").fetchone()[0]
        if tables < 2:
            return 0
        placeholders = ", ".join("?" for _ in UNFINISHED_STATUSES)
        unfinished = conn.execute(f"SELECT EXISTS(SELECT 1 FROM collection_status WHERE status IN ({placeholders}))", UNFINISHED_STATUSES).fetchone()[0]
        if unfinished:
            return 0
        return conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    finally:
        conn.close()


def wait_indexed(profile: str, timeout: float) -> None:
    validate_profile_name(profile)
    db_path = _sample_data_db(profile)
    deadline = time.monotonic() + timeout
    settled_count, settled_since = 0, 0.0
    while True:
        if not AppProcess.list_profile_processes(profile):
            raise RuntimeError(f"Wafer for {profile} exited before {db_path} finished indexing")
        count = _collected_source_count(db_path)
        now = time.monotonic()
        if count and count == settled_count:
            if now - settled_since >= INDEX_SETTLE_SECONDS:
                AppLogger.info(f"{profile}: {count} sources indexed and collected")
                return
        else:
            settled_count, settled_since = count, now
        if now >= deadline:
            raise TimeoutError(f"{profile}: {db_path} was not fully indexed within {timeout:.0f}s")
        time.sleep(INDEX_POLL_SECONDS)


def launch_process(checkout: Path, profile: str) -> int:
    root = _real(checkout)
    if not _is_checkout(root):
        raise ValueError(f"Not a Wafer checkout (main.py and wafer/ are required): {checkout}")
    cmd = [AppProcess.base_command()[0], str(root / "main.py"), PROFILE_ARG, validate_profile_name(profile)]
    proc = AppProcess.spawn(cmd, cwd=str(root))
    AppLogger.info(f"Launched {profile} from {root} (pid={proc.pid})")
    return proc.pid


def _wait_for_exit(profile: str, deadline: float) -> list:
    while True:
        procs = AppProcess.list_profile_processes(profile)
        if not procs or time.monotonic() >= deadline:
            return procs
        time.sleep(STOP_POLL_SECONDS)


def stop_profile(profile: str, timeout: float = 15.0) -> None:
    validate_profile_name(profile)
    if not AppProcess.list_profile_processes(profile):
        return
    AppLogger.info(f"Stopping {profile}")
    deadline = time.monotonic() + timeout
    node = Node("debug", profile=profile)
    node.start()
    try:
        if node.wait_registered(timeout=min(STOP_REGISTER_SECONDS, timeout)):
            node.send("app.quit_all", dst="tray")
            remaining = _wait_for_exit(profile, deadline)
        else:
            AppLogger.warning(f"The broker of {profile} did not answer; terminating its processes")
            remaining = AppProcess.list_profile_processes(profile)
    finally:
        node.stop()
    if remaining:
        AppLogger.warning(f"{len(remaining)} processes of {profile} are still running; terminating them")
        AppProcess.terminate_tree(remaining)
    AppLogger.info(f"Stopped {profile}")


def forget_profile(profile: str) -> None:
    stop_profile(profile)
    for root in {profile_data_root(profile), profile_config_root(profile)}:
        if root.exists():
            shutil.rmtree(root)
            AppLogger.info(f"Deleted {root}")


def _runtime_state_ignorer(root: Path) -> Callable[[str, list[str]], set[str]]:
    root_key = os.path.normcase(os.fspath(root))

    def ignore(directory: str, names: list[str]) -> set[str]:
        if os.path.normcase(directory) != root_key:
            return set()
        return TEMPLATE_EXCLUDED.intersection(names)

    return ignore


def build_template(checkout: Path, *, on_progress: Progress) -> Path:
    digest = schema_hash(checkout)
    target = template_dir(digest)
    with file_lock(_template_lock(digest), timeout=TEMPLATE_LOCK_TIMEOUT):
        if target.is_dir():
            on_progress(f"Sample template {digest} is ready")
            return target
        root = profile_data_root(TEMPLATE_BUILD_PROFILE)
        stop_profile(TEMPLATE_BUILD_PROFILE)
        if root.exists():
            shutil.rmtree(root)
        sample_db_setup(root)
        on_progress(f"Building sample template {digest}: indexing the sample takes a few minutes")
        try:
            launch_process(checkout, TEMPLATE_BUILD_PROFILE)
            wait_indexed(TEMPLATE_BUILD_PROFILE, timeout=TEMPLATE_INDEX_TIMEOUT)
        finally:
            stop_profile(TEMPLATE_BUILD_PROFILE)
        staging = target.with_name(f"{digest}{TEMPLATE_STAGING_SUFFIX}")
        if staging.exists():
            shutil.rmtree(staging)
        shutil.copytree(root, staging, ignore=_runtime_state_ignorer(root))
        staging.rename(target)
        shutil.rmtree(root)
    on_progress(f"Sample template {digest} built")
    return target


def rebuild_template(checkout: Path, *, on_progress: Progress) -> Path:
    digest = schema_hash(checkout)
    target = template_dir(digest)
    with file_lock(_template_lock(digest), timeout=TEMPLATE_LOCK_TIMEOUT):
        if target.exists():
            shutil.rmtree(target)
            AppLogger.info(f"Deleted sample template {target}")
    return build_template(checkout, on_progress=on_progress)


def _prepare_scratch(profile: str, root: Path) -> None:
    scratch = scratch_root(profile)
    scratch.mkdir(parents=True, exist_ok=True)
    source = sample_root() / SCRATCH_SOURCE
    images = sorted((p for p in source.iterdir() if p.is_file()), key=lambda p: p.name)[:SCRATCH_IMAGE_COUNT]
    for image in images:
        shutil.copy2(image, scratch / image.name)
    _add_parent_folder(SettingDB(str(_sample_settings_db(root))), scratch)
    AppLogger.info(f"{profile}: copied {len(images)} sample images into {scratch}")


def ensure_profile(checkout: Path, *, fresh: bool, on_progress: Progress) -> str:
    profile = profile_name_for(checkout)
    template = template_dir(schema_hash(checkout))
    if not template.is_dir():
        template = build_template(checkout, on_progress=on_progress)
    root = profile_data_root(profile)
    if not fresh and _sample_settings_db(root).is_file():
        return profile
    if root.exists():
        stop_profile(profile)
        shutil.rmtree(root)
    on_progress(f"Creating {profile} from sample template {template.name}")
    shutil.copytree(template, root)
    _prepare_scratch(profile, root)
    return profile


def _launch(args: argparse.Namespace) -> None:
    profile = profile_name_for(args.checkout)
    stop_profile(profile)
    ensure_profile(args.checkout, fresh=args.fresh, on_progress=AppLogger.info)
    pid = launch_process(args.checkout, profile)
    AppLogger.info(f"{profile} is starting (pid={pid})")


def _stop(args: argparse.Namespace) -> None:
    stop_profile(args.name)


def _forget(args: argparse.Namespace) -> None:
    forget_profile(args.name)


def _rebuild_template(args: argparse.Namespace) -> None:
    target = rebuild_template(args.checkout, on_progress=AppLogger.info)
    AppLogger.info(f"Sample template rebuilt at {target}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m debug.profile_setup", description="Prepare, launch and stop debug profiles of Wafer.")
    commands = parser.add_subparsers(dest="command", required=True)
    launch = commands.add_parser("launch", help="Launch the checkout's debug profile, creating it from the sample template if needed.")
    launch.add_argument("--checkout", type=Path, required=True)
    launch.add_argument("--fresh", action="store_true", help="Recreate the profile from the template.")
    launch.set_defaults(func=_launch)
    stop = commands.add_parser("stop", help="Quit every process of a debug profile.")
    stop.add_argument("name")
    stop.set_defaults(func=_stop)
    forget = commands.add_parser("forget", help="Stop a debug profile and delete its data.")
    forget.add_argument("name")
    forget.set_defaults(func=_forget)
    rebuild = commands.add_parser("rebuild-template", help="Rebuild the sample template for the checkout's schema.")
    rebuild.add_argument("--checkout", type=Path, required=True)
    rebuild.set_defaults(func=_rebuild_template)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        args.func(args)
    except ValueError as exc:
        AppLogger.error(f"{args.command}: {exc}")
        return 1
    except (RuntimeError, TimeoutError, OSError) as exc:
        AppLogger.error(f"{args.command} failed: {exc}", exc=exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
