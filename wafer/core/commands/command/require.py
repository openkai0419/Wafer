from __future__ import annotations

import functools
from typing import Callable

from ....utils.notifier import Notifier


def require(**instances: str) -> Callable:
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(ctx, *args, **kwargs):
            for param_name, instance_name in instances.items():
                val = ctx.get_instance(instance_name)
                if val is None:
                    Notifier.warning(f"{instance_name} is not available")
                    return None
                kwargs[param_name] = val
            return func(ctx, *args, **kwargs)
        return wrapper
    return decorator


def require_v(**values: str) -> Callable:
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(ctx, *args, **kwargs):
            for param_name, key in values.items():
                val = ctx.get(key)
                if not val:
                    return None
                kwargs[param_name] = val
            return func(ctx, *args, **kwargs)
        return wrapper
    return decorator
