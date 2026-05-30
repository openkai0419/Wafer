import py_compile
import threading
import time

import pytest

from wafer.app.indexer.scheduler import TaskScheduler, PeriodicTask, _QUEUE_POLL_INTERVAL, _IMMEDIATE_THRESHOLD
from wafer.app.indexer.task import Task, TaskPriority


def test_compile():
    py_compile.compile("wafer/app/indexer/scheduler.py")


@pytest.fixture
def scheduler():
    s = TaskScheduler()
    s.start()
    yield s
    s.stop()


def test_start_and_stop():
    s = TaskScheduler()
    s.start()
    assert s._immediate_thread is not None
    assert s._immediate_thread.is_alive()
    assert s._background_thread is not None
    assert s._background_thread.is_alive()
    s.stop()
    assert not s._immediate_thread.is_alive()
    assert not s._background_thread.is_alive()


def test_submit_and_execute(scheduler):
    done = threading.Event()
    results = []
    scheduler.submit(
        Task.create(
            "test_op",
            run=lambda: results.append("ran"),
            on_complete=done.set,
        )
    )
    assert done.wait(timeout=5.0)
    assert results == ["ran"]


def test_priority_ordering_within_background_lane(scheduler):
    execution_order = []
    lock = threading.Lock()
    barrier = threading.Event()

    scheduler.submit(
        Task.create(
            "blocker",
            priority=TaskPriority.SCAN,
            run=lambda: barrier.wait(5.0),
        )
    )
    time.sleep(0.2)

    scheduler.submit(
        Task.create(
            "low",
            priority=TaskPriority.MAINTENANCE,
            run=lambda: (lock.acquire(), execution_order.append("low"), lock.release()),
        )
    )
    done = threading.Event()
    scheduler.submit(
        Task.create(
            "high",
            priority=TaskPriority.SCAN,
            run=lambda: (lock.acquire(), execution_order.append("high"), lock.release()),
            on_complete=done.set,
        )
    )

    barrier.set()
    assert done.wait(timeout=5.0)
    time.sleep(0.3)

    with lock:
        if "high" in execution_order and "low" in execution_order:
            assert execution_order.index("high") < execution_order.index("low")


def test_on_complete_callback(scheduler):
    results = []
    done = threading.Event()

    scheduler.submit(
        Task.create(
            "op",
            run=lambda: None,
            on_complete=lambda: (results.append("called"), done.set()),
        )
    )
    assert done.wait(timeout=5.0)
    assert results == ["called"]


def test_on_complete_error_does_not_crash(scheduler):
    done = threading.Event()

    scheduler.submit(
        Task.create(
            "bad_cb",
            run=lambda: None,
            on_complete=lambda: (_ for _ in ()).throw(ValueError("test error")),
        )
    )
    scheduler.submit(
        Task.create(
            "good_cb",
            run=lambda: None,
            on_complete=done.set,
        )
    )
    assert done.wait(timeout=5.0)


def test_cancelled_task_skipped(scheduler):
    from wafer.app.indexer.task import CancelToken

    ran = []
    done = threading.Event()

    token = CancelToken()
    token.cancel()

    scheduler.submit(
        Task.create(
            "cancelled_op",
            run=lambda: ran.append("should_not_run"),
            cancel_token=token,
        )
    )
    scheduler.submit(
        Task.create(
            "after",
            run=lambda: None,
            on_complete=done.set,
        )
    )
    assert done.wait(timeout=5.0)
    assert ran == []


def test_periodic_task():
    task = PeriodicTask(
        name="test_task",
        interval=1.0,
        create_task=lambda: Task.create("op", run=lambda: None),
    )
    now = time.monotonic()
    task.last_run = now - 2.0
    assert task.should_run(now, idle_duration=0.0)
    task.last_run = now
    assert not task.should_run(now, idle_duration=0.0)


def test_periodic_task_idle_delay():
    task = PeriodicTask(
        name="cleanup",
        interval=1.0,
        create_task=lambda: Task.create("purge", priority=TaskPriority.MAINTENANCE, run=lambda: None),
        idle_delay=300.0,
    )
    now = time.monotonic()
    task.last_run = now - 2.0
    assert not task.should_run(now, idle_duration=60.0)
    assert task.should_run(now, idle_duration=300.0)
    assert task.should_run(now, idle_duration=600.0)


def test_idle_detection():
    s = TaskScheduler()
    s.start()

    triggered = threading.Event()
    s.add_periodic_task(
        PeriodicTask(
            name="idle_check",
            interval=0.0,
            create_task=lambda: Task.create(
                "idle_op",
                priority=TaskPriority.MAINTENANCE,
                run=lambda: None,
                on_complete=triggered.set,
            ),
            idle_delay=0.1,
        )
    )

    s._last_active_time = time.monotonic() - 1.0
    assert triggered.wait(timeout=5.0)
    s.stop()


def test_idle_base_delay_is_applied_before_periodic_idle_delay():
    task = PeriodicTask(
        name="idle_base_check",
        interval=0.0,
        create_task=lambda: Task.create("op", priority=TaskPriority.MAINTENANCE, run=lambda: None),
        idle_delay=60.0,
    )
    s = TaskScheduler()
    s.set_idle_base_delay(1200.0)
    s.add_periodic_task(task)
    s._last_active_time = time.monotonic() - 1259.0
    s._check_periodic_tasks()
    assert s._background_queue.empty()
    s._last_active_time = time.monotonic() - 1261.0
    s._check_periodic_tasks()
    assert not s._background_queue.empty()


def test_is_idle_respects_idle_base_delay():
    s = TaskScheduler()
    s.set_idle_base_delay(1200.0)
    s._last_active_time = time.monotonic() - 1199.0
    assert not s.is_idle()
    s._last_active_time = time.monotonic() - 1201.0
    assert s.is_idle()


def test_multiple_submits(scheduler):
    done = threading.Event()
    count = {"n": 0}
    lock = threading.Lock()

    def inc():
        with lock:
            count["n"] += 1
            if count["n"] >= 10:
                done.set()

    for _ in range(10):
        scheduler.submit(
            Task.create(
                "op",
                run=lambda: None,
                on_complete=inc,
            )
        )

    assert done.wait(timeout=10.0)
    assert count["n"] == 10


def test_is_idle_false_while_task_is_running(scheduler):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    scheduler.submit(
        Task.create(
            "blocker",
            priority=TaskPriority.SCAN,
            run=lambda: (started.set(), release.wait(5.0)),
            on_complete=finished.set,
        )
    )

    assert started.wait(timeout=5.0)
    assert not scheduler.is_idle()

    release.set()
    assert finished.wait(timeout=5.0)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if scheduler.is_idle():
            break
        time.sleep(0.01)
    assert scheduler.is_idle()


def test_cancel_all_cancels_tracked_tokens(scheduler):
    from wafer.app.indexer.task import CancelToken

    tokens = [CancelToken() for _ in range(3)]
    for i, tok in enumerate(tokens):
        scheduler.submit(Task.create(f"op_{i}", cancel_token=tok, run=lambda: None))
    scheduler.cancel_all()
    for tok in tokens:
        assert tok.is_cancelled


def test_cancel_all_drains_queue(scheduler):
    barrier = threading.Event()
    scheduler.submit(
        Task.create(
            "blocker",
            priority=TaskPriority.REALTIME,
            run=lambda: barrier.wait(5.0),
        )
    )
    time.sleep(0.2)
    for i in range(5):
        scheduler.submit(Task.create(f"pending_{i}", run=lambda: None))
    scheduler.cancel_all()
    barrier.set()
    time.sleep(0.5)
    assert scheduler._immediate_queue.empty()
    assert scheduler._background_queue.empty()


def test_cancel_all_then_submit_new_task(scheduler):
    scheduler.cancel_all()
    done = threading.Event()
    scheduler.submit(Task.create("after_cancel", run=lambda: None, on_complete=done.set))
    assert done.wait(timeout=5.0)


def test_stop_from_task_thread_no_hang():
    s = TaskScheduler()
    s.start()
    done = threading.Event()
    s.submit(Task.create("self_stop", run=lambda: (s.stop(), done.set())))
    assert done.wait(timeout=5.0)
    s._background_thread.join(timeout=2.0)
    assert not s._background_thread.is_alive()


@pytest.mark.parametrize(
    "priority,resets",
    [
        (TaskPriority.SCAN, True),
        (TaskPriority.COLLECTION, True),
        (TaskPriority.DISPATCH, True),
        (TaskPriority.RETRY, False),
        (TaskPriority.MAINTENANCE, False),
    ],
)
def test_idle_timer_reset_by_priority(priority, resets):
    s = TaskScheduler()
    s.start()
    stale = time.monotonic() - 600
    s._last_active_time = stale
    done = threading.Event()
    s.submit(Task.create("op", priority=priority, run=lambda: None, on_complete=done.set))
    assert done.wait(timeout=5.0)
    time.sleep(0.1)
    if resets:
        assert s._last_active_time > stale
    else:
        assert s._last_active_time == stale
    s.stop()


def test_once_per_idle_fires_once_then_suppressed():
    task = PeriodicTask(
        name="once_check",
        interval=0.0,
        idle_delay=0.0,
        once_per_idle=True,
        create_task=lambda: Task.create("op", priority=TaskPriority.MAINTENANCE, run=lambda: None),
    )
    now = time.monotonic()
    assert task.should_run(now, idle_duration=10.0)
    task._idle_done = True
    task.last_run = now - 1.0
    assert not task.should_run(now, idle_duration=10.0)


def test_once_per_idle_resets_on_active_task():
    s = TaskScheduler()
    s.start()

    run_count = {"n": 0}
    s.add_periodic_task(
        PeriodicTask(
            name="once_task",
            interval=0.0,
            idle_delay=0.0,
            once_per_idle=True,
            create_task=lambda: Task.create(
                "maint",
                priority=TaskPriority.MAINTENANCE,
                run=lambda: None,
                on_complete=lambda: run_count.__setitem__("n", run_count["n"] + 1),
            ),
        )
    )

    s._last_active_time = time.monotonic() - 100
    time.sleep(3.0)
    first_count = run_count["n"]
    assert first_count >= 1

    time.sleep(2.0)
    assert run_count["n"] == first_count

    done = threading.Event()
    s.submit(Task.create("work", priority=TaskPriority.SCAN, run=lambda: None, on_complete=done.set))
    assert done.wait(timeout=5.0)

    s._last_active_time = time.monotonic() - 100
    time.sleep(3.0)
    assert run_count["n"] > first_count

    s.stop()


# ── 2-lane specific tests ──────────────────────────────────────


def test_immediate_task_routes_to_immediate_queue():
    s = TaskScheduler()
    t = Task.create("rt", priority=TaskPriority.REALTIME, run=lambda: None)
    s.submit(t)
    assert not s._immediate_queue.empty()
    assert s._background_queue.empty()


def test_background_task_routes_to_background_queue():
    s = TaskScheduler()
    t = Task.create("scan", priority=TaskPriority.SCAN, run=lambda: None)
    s.submit(t)
    assert s._immediate_queue.empty()
    assert not s._background_queue.empty()


def test_threshold_boundary():
    s = TaskScheduler()
    below = Task.create("user_req", priority=TaskPriority.USER_REQUEST, run=lambda: None)
    at = Task.create("scan", priority=TaskPriority.SCAN, run=lambda: None)
    s.submit(below)
    s.submit(at)
    assert not s._immediate_queue.empty()
    assert not s._background_queue.empty()


def test_immediate_not_blocked_by_background(scheduler):
    bg_barrier = threading.Event()
    immediate_done = threading.Event()

    scheduler.submit(
        Task.create(
            "slow_scan",
            priority=TaskPriority.SCAN,
            run=lambda: bg_barrier.wait(10.0),
        )
    )
    time.sleep(0.1)

    start = time.monotonic()
    scheduler.submit(
        Task.create(
            "user_op",
            priority=TaskPriority.USER_REQUEST,
            run=lambda: None,
            on_complete=immediate_done.set,
        )
    )
    assert immediate_done.wait(timeout=3.0)
    elapsed = time.monotonic() - start
    assert elapsed < 2.0

    bg_barrier.set()


def test_both_lanes_execute_concurrently(scheduler):
    bg_started = threading.Event()
    bg_release = threading.Event()
    im_done = threading.Event()

    scheduler.submit(
        Task.create(
            "bg_task",
            priority=TaskPriority.SCAN,
            run=lambda: (bg_started.set(), bg_release.wait(10.0)),
        )
    )
    assert bg_started.wait(timeout=5.0)

    scheduler.submit(
        Task.create(
            "im_task",
            priority=TaskPriority.REALTIME,
            run=lambda: None,
            on_complete=im_done.set,
        )
    )
    assert im_done.wait(timeout=3.0)

    bg_release.set()


def test_immediate_lane_resets_idle_timer(scheduler):
    stale = time.monotonic() - 600
    scheduler._last_active_time = stale
    done = threading.Event()
    scheduler.submit(
        Task.create(
            "rt_op",
            priority=TaskPriority.REALTIME,
            run=lambda: None,
            on_complete=done.set,
        )
    )
    assert done.wait(timeout=5.0)
    time.sleep(0.1)
    assert scheduler._last_active_time > stale
