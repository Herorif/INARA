"""Load optional capabilities only when they are actually requested."""

from importlib import import_module


class LazyService:
    def __init__(self, module, attribute=None, **kwargs):
        self.module = module
        self.attribute = attribute
        self.kwargs = kwargs
        self.instance = None

    def get(self):
        if self.instance is None:
            module = import_module(self.module)
            factory = getattr(module, self.attribute) if self.attribute else None
            self.instance = factory(**self.kwargs) if factory else module
        return self.instance

    def __getattr__(self, name):
        return getattr(self.get(), name)
