from ..common.profiling import logger, profiler

class AutoRegister(type):
    def __init__(cls, name, bases, ns):
        super().__init__(name, bases, ns)
        if hasattr(cls, 'is_readable'):
            ReaderClass.add(cls)
        if hasattr(cls, 'is_loadable'):
            LoaderClass.add(cls)

class BaseReader(metaclass=AutoRegister):
    pass

class BaseLoader(metaclass=AutoRegister):
    pass

class ReaderClass:
    _readers = []

    @classmethod
    def read(cls, path):
        for reader in cls._readers:
            if reader.is_readable(path):
                return reader().read(path)

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
