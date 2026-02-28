import threading
from source.utils.decorators import singleton


def test_singleton_returns_same_instance():
    @singleton
    class MyClass:
        pass

    a = MyClass()
    b = MyClass()
    assert a is b


def test_singleton_preserves_init_args():
    @singleton
    class Counter:
        def __init__(self, start=0):
            self.value = start

    c1 = Counter(10)
    c2 = Counter(99)
    assert c1.value == 10
    assert c2 is c1


def test_singleton_thread_safe():
    @singleton
    class Shared:
        def __init__(self):
            self.x = 0

    results = []

    def get_instance():
        results.append(id(Shared()))

    threads = [threading.Thread(target=get_instance) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(set(results)) == 1


def test_singleton_preserves_class_name():
    @singleton
    class Named:
        pass

    assert Named.__name__ == "Named"
