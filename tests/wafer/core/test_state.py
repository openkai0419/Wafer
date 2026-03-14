import threading

import pytest
from wafer.core.state import StateStore


@pytest.fixture(autouse=True)
def clean_state_store():
    store = StateStore.instance()
    store.clear()
    yield
    store.clear()
    StateStore._instance = None


class TestStateStore:

    def test_instance_singleton(self):
        a = StateStore.instance()
        b = StateStore.instance()
        assert a is b

    def test_register_and_save(self):
        store = StateStore.instance()
        store.register('ns1', lambda: {'k': 'v'}, lambda s: None)
        result = store.save_all()
        assert result == {'ns1': {'k': 'v'}}

    def test_save_skips_empty(self):
        store = StateStore.instance()
        store.register('ns1', lambda: {}, lambda s: None)
        store.register('ns2', lambda: {'a': 1}, lambda s: None)
        result = store.save_all()
        assert 'ns1' not in result
        assert result == {'ns2': {'a': 1}}

    def test_restore_calls_registered(self):
        store = StateStore.instance()
        received = {}
        store.register('ns1', lambda: {}, lambda s: received.update(s))
        store.restore_all({'ns1': {'x': 42}})
        assert received == {'x': 42}

    def test_restore_pending_on_late_register(self):
        store = StateStore.instance()
        store.restore_all({'late_ns': {'val': 99}})

        received = {}
        store.register('late_ns', lambda: {}, lambda s: received.update(s))
        assert received == {'val': 99}

    def test_pending_cleared_after_register(self):
        store = StateStore.instance()
        store.restore_all({'ns': {'a': 1}})
        received_1 = {}
        store.register('ns', lambda: {}, lambda s: received_1.update(s))
        assert received_1 == {'a': 1}

        received_2 = {}
        store.unregister('ns')
        store.register('ns', lambda: {}, lambda s: received_2.update(s))
        assert received_2 == {}

    def test_unregister_removes_entry(self):
        store = StateStore.instance()
        store.register('ns', lambda: {'data': True}, lambda s: None)
        store.unregister('ns')
        assert store.save_all() == {}

    def test_restore_all_clears_old_pending(self):
        store = StateStore.instance()
        store.restore_all({'old': {'a': 1}})
        store.restore_all({'new': {'b': 2}})

        old_received = {}
        store.register('old', lambda: {}, lambda s: old_received.update(s))
        assert old_received == {}

        new_received = {}
        store.register('new', lambda: {}, lambda s: new_received.update(s))
        assert new_received == {'b': 2}

    def test_restore_skips_non_dict_values(self):
        store = StateStore.instance()
        received = {}
        store.register('ns', lambda: {}, lambda s: received.update(s))
        store.restore_all({'ns': 'not_a_dict', 'ns2': 123})
        assert received == {}

    def test_save_exception_handled(self):
        store = StateStore.instance()
        store.register('bad', lambda: (_ for _ in ()).throw(ValueError("fail")), lambda s: None)
        store.register('good', lambda: {'ok': True}, lambda s: None)
        result = store.save_all()
        assert 'bad' not in result
        assert result == {'good': {'ok': True}}

    def test_restore_exception_handled(self):
        store = StateStore.instance()

        def failing_restore(s):
            raise RuntimeError("restore failed")

        store.register('bad', lambda: {}, failing_restore)
        store.register('good', lambda: {}, lambda s: None)
        store.restore_all({'bad': {'x': 1}, 'good': {'y': 2}})

    def test_deferred_restore_exception_handled(self):
        store = StateStore.instance()
        store.restore_all({'ns': {'fail': True}})

        def failing_restore(s):
            raise RuntimeError("deferred fail")

        store.register('ns', lambda: {}, failing_restore)

    def test_clear(self):
        store = StateStore.instance()
        store.register('ns', lambda: {'a': 1}, lambda s: None)
        store.restore_all({'pending': {'b': 2}})
        store.clear()
        assert store.save_all() == {}
        received = {}
        store.register('pending', lambda: {}, lambda s: received.update(s))
        assert received == {}

    def test_multiple_namespaces(self):
        store = StateStore.instance()
        store.register('video', lambda: {'volume': 75}, lambda s: None)
        store.register('grid', lambda: {'zoom': 200}, lambda s: None)
        store.register('file_viewer', lambda: {'fit_mode': 'contain'}, lambda s: None)
        result = store.save_all()
        assert result == {
            'video': {'volume': 75},
            'grid': {'zoom': 200},
            'file_viewer': {'fit_mode': 'contain'},
        }

    def test_roundtrip(self):
        store = StateStore.instance()
        state_a = {'volume': 80, 'muted': True}
        state_b = {'fit_mode': 'cover'}
        received_a = {}
        received_b = {}

        store.register('a', lambda: state_a, lambda s: received_a.update(s))
        store.register('b', lambda: state_b, lambda s: received_b.update(s))

        saved = store.save_all()
        store.restore_all(saved)

        assert received_a == {'volume': 80, 'muted': True}
        assert received_b == {'fit_mode': 'cover'}

    def test_save_all_safe_during_unregister(self):
        store = StateStore.instance()
        barrier = threading.Barrier(2, timeout=2)
        results = {}

        def slow_save():
            barrier.wait()
            return {'slow': True}

        store.register('will_remove', lambda: {'x': 1}, lambda s: None)
        store.register('slow', slow_save, lambda s: None)

        def bg():
            results['saved'] = store.save_all()

        t = threading.Thread(target=bg)
        t.start()
        barrier.wait()
        store.unregister('will_remove')
        t.join(timeout=3)
        assert 'slow' in results['saved']

    def test_concurrent_register_restore(self):
        store = StateStore.instance()
        store.restore_all({'ns_a': {'v': 1}, 'ns_b': {'v': 2}})
        received = {}

        def register_a():
            store.register('ns_a', lambda: {}, lambda s: received.update({'a': s}))

        def register_b():
            store.register('ns_b', lambda: {}, lambda s: received.update({'b': s}))

        t1 = threading.Thread(target=register_a)
        t2 = threading.Thread(target=register_b)
        t1.start()
        t2.start()
        t1.join(timeout=2)
        t2.join(timeout=2)
        assert received.get('a') == {'v': 1}
        assert received.get('b') == {'v': 2}
