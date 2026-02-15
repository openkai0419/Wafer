from ..common.profiling import profiler
from ..common.logs import AppLogger

class AutoRegister(type):
    def __init__(cls, name, bases, ns):
        super().__init__(name, bases, ns)
        if hasattr(cls, 'is_readable'):
            ReaderClass.add(cls)
        if hasattr(cls, 'is_loadable'):
            LoaderClass.add(cls)

class ReaderClass:
    _readers = []

    @classmethod
    def read(cls, path, *args, **kwargs):
        for reader in cls._readers:
            if reader.is_readable(path):
                return reader().read(path, *args, **kwargs)

    @classmethod    
    def add(cls, cl):
        cls._readers.append(cl)

class LoaderClass:
    _loaders = []

    @classmethod
    def load(cls, path, *args, **kwargs):
        for loader in cls._loaders:
            if loader.is_loadable(path):
                return loader().load(path, *args, **kwargs)
    
    @classmethod 
    def add(cls, cl):
        cls._loaders.append(cl)

class BaseReader(metaclass=AutoRegister):
    def read(path, *args, **kwargs):
        return None
    
    def is_readable(path):
        return False

class BaseLoader(metaclass=AutoRegister):
    def load(path, *args, **kwargs):
        return None
    
    def is_loadable(path):
        return False
