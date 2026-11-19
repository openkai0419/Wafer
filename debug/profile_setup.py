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
from typing import NamedTuple

from wafer.app.indexer.scanner import files_in_scope
from wafer.core.common.paths import (
    debug_profiles_dir,
    normalize_path,
    profile_config_root,
    profile_data_root,
    sample_root,
    scratch_root,
)
from wafer.core.common.profile import PROFILE_ARG, PROFILE_PREFIX, TOOLS_PROFILE, validate_profile_name
from wafer.core.db.db_utils import open_readonly
from wafer.core.db.setting_db import SettingDB
from wafer.core.ipc.node import Node
from wafer.core.logs import AppLogger
from wafer.core.platform.process import AppProcess
from wafer.core.platform.process_lock import file_lock

MAIN_PROFILE = f"{PROFILE_PREFIX}main"
TEMPLATE_BUILD_PROFILE = f"{PROFILE_PREFIX}template-build"
TEMPLATE_DIR_NAME = "_template"
STAGING_SUFFIX = ".partial"
TRASH_SUFFIX = ".trash"
PROFILE_READY_MARKER = ".profile-ready"
PROFILE_LOCK_TIMEOUT = 300.0
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
RESERVED_WORKTREE_NAMES = {
    MAIN_PROFILE.removeprefix(PROFILE_PREFIX): "the main checkout's profile",
    TEMPLATE_BUILD_PROFILE.removeprefix(PROFILE_PREFIX): "the profile that builds the sample template",
    TOOLS_PROFILE.removeprefix(PROFILE_PREFIX): "the profile the debug tooling (MCP server, this CLI) runs under",
}

SAMPLE_FIX_HINT = (
    "In a worktree, restore its .sample link with `python scripts/worktree.py repair <task>` from the main checkout; "
    "in the main checkout, create the sample with `python tests/dataset_downloader.py`; "
    "or point WAFER_DEBUG_SAMPLE_ROOT at a sample folder."
)

Progress = Callable[[str], None]


class SampleUnavailable(RuntimeError):
    pass


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
    for reserved, used_by in RESERVED_WORKTREE_NAMES.items():
        if path.name.casefold() == reserved.casefold():
            raise ValueError(f"Worktree name {path.name!r} is reserved: {PROFILE_PREFIX}{reserved} is {used_by}")
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


def _sample_scope_rules(sample: Path) -> tuple[list[Path], list[str], list[str]]:
    ignored_folders = [str(sample / folder) for folder in SAMPLE_IGNORED_FOLDERS]
    ignored_patterns = [f"{glob.escape(normalize_path(sample))}/{SAMPLE_IGNORED_PATTERN}"]
    return [sample], ignored_folders, ignored_patterns


def require_sample_root() -> Path:
    sample = sample_root()
    if not sample.is_dir():
        raise SampleUnavailable(f"The debug sample folder {sample} is missing. {SAMPLE_FIX_HINT}")
    try:
        with os.scandir(sample) as entries:
            next(entries, None)
    except OSError as e:
        raise SampleUnavailable(f"The debug sample folder {sample} cannot be listed ({e}). {SAMPLE_FIX_HINT}") from e
    return sample


def require_sample() -> Path:
    sample = require_sample_root()
    roots, ignored_folders, ignored_patterns = _sample_scope_rules(sample)
    if not files_in_scope([str(root) for root in roots], ignored_folders, ignored_patterns):
        raise SampleUnavailable(f"The debug sample folder {sample} has no files to index. {SAMPLE_FIX_HINT}")
    return sample


def sample_db_setup(root: Path) -> None:
    sample = require_sample_root()
    db_path = _sample_settings_db(root)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    roots, ignored_folders, ignored_patterns = _sample_scope_rules(sample)
    settings = SettingDB(str(db_path))
    for folder in roots:
        _add_parent_folder(settings, folder)
    for folder in ignored_folders:
        settings.add_ignore_folder(folder)
    for pattern in ignored_patterns:
        settings.add_ignore_pattern(pattern)
    AppLogger.info(f"Sample DB settings written to {db_path} (sample root {sample})")


class IndexState(NamedTuple):
    sources: int
    uncollected: int
    unfinished: int
    rows: int

    def is_complete(self, expected: int) -> bool:
        return self.sources == expected and not self.uncollected and not self.unfinished

    def describe(self, expected: int) -> str:
        return f"{self.sources} of {expected} sources, {self.uncollected} without collection rows, {self.unfinished} rows pending or dispatched"


EMPTY_INDEX = IndexState(0, 0, 0, 0)


def _index_state(db_path: Path) -> IndexState:
    if not db_path.is_file():
        return EMPTY_INDEX
    conn = open_readonly(db_path)
    try:
        tables = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name IN ('sources', 'collection_status')").fetchone()[0]
        if tables < 2:
            return EMPTY_INDEX
        placeholders = ", ".join("?" for _ in UNFINISHED_STATUSES)
        row = conn.execute(
            f"""SELECT
                (SELECT COUNT(*) FROM sources),
                (SELECT COUNT(*) FROM sources s WHERE NOT EXISTS (SELECT 1 FROM collection_status cs WHERE cs.source = s.source)),
                (SELECT COUNT(*) FROM collection_status WHERE status IN ({placeholders})),
                (SELECT COUNT(*) FROM collection_status)""",
            UNFINISHED_STATUSES,
        ).fetchone()
        return IndexState(*row)
    finally:
        conn.close()


def expected_source_count(settings_db: Path) -> int:
    if not settings_db.is_file():
        raise FileNotFoundError(f"No sample DB settings at {settings_db}")
    roots, ignore_folders, ignore_patterns = SettingDB(str(settings_db)).get_all_folder_settings()
    return len(files_in_scope(roots, ignore_folders, ignore_patterns))


def sample_scope_count(profile: str) -> int:
    settings_db = _sample_settings_db(profile_data_root(validate_profile_name(profile)))
    sample = require_sample_root()
    count = expected_source_count(settings_db)
    if not count:
        raise SampleUnavailable(f"{profile} has no files to index under {sample} or its other folders. {SAMPLE_FIX_HINT}")
    return count


def sample_index_state(profile: str) -> IndexState:
    return _index_state(_sample_data_db(validate_profile_name(profile)))


def wait_indexed(profile: str, timeout: float) -> None:
    db_path = _sample_data_db(validate_profile_name(profile))
    expected = sample_scope_count(profile)
    AppLogger.info(f"{profile}: waiting until {expected} sources are indexed and collected")
    deadline = time.monotonic() + timeout
    settled: IndexState | None = None
    settled_since = 0.0
    while True:
        if not AppProcess.list_profile_processes(profile):
            raise RuntimeError(f"Wafer for {profile} exited before {db_path} finished indexing")
        state = sample_index_state(profile)
        now = time.monotonic()
        if state != settled:
            settled, settled_since = state, now
        elif state.is_complete(expected) and now - settled_since >= INDEX_SETTLE_SECONDS:
            AppLogger.info(f"{profile}: {state.sources} sources indexed and collected ({state.rows} collection rows)")
            return
        if now >= deadline:
            raise TimeoutError(f"{profile}: {db_path} was not fully indexed within {timeout:.0f}s: {state.describe(expected)}")
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


def _profile_lock(profile: str) -> str:
    return str(debug_profiles_dir() / f"{validate_profile_name(profile)}.lock")


def _sweep_trash(path: Path) -> None:
    base = debug_profiles_dir()
    folders = {base, base / TEMPLATE_DIR_NAME, path.parent}
    for leftover in (leftover for folder in folders for leftover in folder.glob(f"*{TRASH_SUFFIX}-*")):
        try:
            shutil.rmtree(leftover)
        except OSError as exc:
            AppLogger.warning(f"Could not delete {leftover} yet; nothing uses it: {exc}")


def _discard(path: Path) -> None:
    trash = path.with_name(f"{path.name}{TRASH_SUFFIX}-{os.getpid()}-{time.time_ns()}")
    path.rename(trash)
    _sweep_trash(path)
    AppLogger.info(f"Deleted {path}")


def forget_profile(profile: str) -> None:
    with file_lock(_profile_lock(profile), timeout=PROFILE_LOCK_TIMEOUT):
        stop_profile(profile)
        for root in {profile_data_root(profile), profile_config_root(profile)}:
            if root.exists():
                _discard(root)


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
        require_sample()
        root = profile_data_root(TEMPLATE_BUILD_PROFILE)
        stop_profile(TEMPLATE_BUILD_PROFILE)
        if root.exists():
            _discard(root)
        sample_db_setup(root)
        on_progress(f"Building sample template {digest}: indexing the sample takes a few minutes")
        try:
            launch_process(checkout, TEMPLATE_BUILD_PROFILE)
            wait_indexed(TEMPLATE_BUILD_PROFILE, timeout=TEMPLATE_INDEX_TIMEOUT)
        finally:
            stop_profile(TEMPLATE_BUILD_PROFILE)
        staging = target.with_name(f"{digest}{STAGING_SUFFIX}")
        if staging.exists():
            _discard(staging)
        shutil.copytree(root, staging, ignore=_runtime_state_ignorer(root))
        staging.rename(target)
        _discard(root)
    on_progress(f"Sample template {digest} built")
    return target


def rebuild_template(checkout: Path, *, on_progress: Progress) -> Path:
    require_sample()
    digest = schema_hash(checkout)
    target = template_dir(digest)
    with file_lock(_template_lock(digest), timeout=TEMPLATE_LOCK_TIMEOUT):
        if target.exists():
            _discard(target)
    return build_template(checkout, on_progress=on_progress)


def _prepare_scratch(profile: str, staging: Path) -> None:
    scratch = scratch_root(profile)
    staged_scratch = staging / scratch.relative_to(profile_data_root(profile))
    staged_scratch.mkdir(parents=True, exist_ok=True)
    source = sample_root() / SCRATCH_SOURCE
    images = sorted((p for p in source.iterdir() if p.is_file()), key=lambda p: p.name)[:SCRATCH_IMAGE_COUNT]
    for image in images:
        shutil.copy2(image, staged_scratch / image.name)
    _add_parent_folder(SettingDB(str(_sample_settings_db(staging))), scratch)
    AppLogger.info(f"{profile}: copied {len(images)} sample images into {scratch}")


def ensure_profile(checkout: Path, *, fresh: bool, on_progress: Progress) -> str:
    profile = profile_name_for(checkout)
    require_sample()
    template = template_dir(schema_hash(checkout))
    if not template.is_dir():
        template = build_template(checkout, on_progress=on_progress)
    root = profile_data_root(profile)
    with file_lock(_profile_lock(profile), timeout=PROFILE_LOCK_TIMEOUT):
        if not fresh and (root / PROFILE_READY_MARKER).is_file():
            return profile
        on_progress(f"Creating {profile} from sample template {template.name}")
        staging = root.with_name(f"{root.name}{STAGING_SUFFIX}")
        if staging.exists():
            _discard(staging)
        shutil.copytree(template, staging)
        _prepare_scratch(profile, staging)
        (staging / PROFILE_READY_MARKER).write_text(template.name, encoding="utf-8")
        if root.exists():
            stop_profile(profile)
            _discard(root)
        staging.rename(root)
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
    tooling = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    tooling.add_argument(
        PROFILE_ARG,
        choices=[TOOLS_PROFILE],
        default=argparse.SUPPRESS,
        help=f"Required, always {TOOLS_PROFILE}: keeps this tool's own logs out of the normal Wafer's data folder.",
    )
    parser = argparse.ArgumentParser(
        prog="python -m debug.profile_setup",
        description=f"Prepare, launch and stop debug profiles of Wafer. Always pass {PROFILE_ARG} {TOOLS_PROFILE}.",
        parents=[tooling],
        allow_abbrev=False,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    launch = commands.add_parser("launch", parents=[tooling], allow_abbrev=False, help="Launch the checkout's debug profile, creating it from the sample template if needed.")
    launch.add_argument("--checkout", type=Path, required=True)
    launch.add_argument("--fresh", action="store_true", help="Recreate the profile from the template.")
    launch.set_defaults(func=_launch)
    stop = commands.add_parser("stop", parents=[tooling], allow_abbrev=False, help="Quit every process of a debug profile.")
    stop.add_argument("name")
    stop.set_defaults(func=_stop)
    forget = commands.add_parser("forget", parents=[tooling], allow_abbrev=False, help="Stop a debug profile and delete its data.")
    forget.add_argument("name")
    forget.set_defaults(func=_forget)
    rebuild = commands.add_parser("rebuild-template", parents=[tooling], allow_abbrev=False, help="Rebuild the sample template for the checkout's schema.")
    rebuild.add_argument("--checkout", type=Path, required=True)
    rebuild.set_defaults(func=_rebuild_template)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "profile"):
        parser.error(f"the following arguments are required: {PROFILE_ARG} {TOOLS_PROFILE}")
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
