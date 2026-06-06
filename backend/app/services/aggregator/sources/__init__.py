"""资源站点注册表与工厂函数。"""

from __future__ import annotations

import threading

from .base import BaseSource
from .bt7274 import BT7274Source
from .btbtla import BtbtlaSource
from .rarbt import RarbtSource
from .yinfans import YinfansSource
from .renrenys import RenrenysSource
from .hdzu import HdzuSource
from .fourk_zhinan import FourKZhinanSource

# 站点注册表：name -> class
_REGISTRY: dict[str, type[BaseSource]] = {
    "bt7274": BT7274Source,
    "btbtla": BtbtlaSource,
    "rarbt": RarbtSource,
    "yinfans": YinfansSource,
    "renrenys": RenrenysSource,
    "hdzu": HdzuSource,
    "4kzhinan": FourKZhinanSource,
}

# 单例缓存
_INSTANCES: dict[str, BaseSource] = {}
_INSTANCES_LOCK = threading.Lock()

# 所有支持的站点名
SOURCE_NAMES: list[str] = list(_REGISTRY.keys())

# 按优先级排序的站点名
SOURCE_PRIORITY: list[str] = sorted(_REGISTRY.keys(), key=lambda n: _REGISTRY[n].priority)


def get_source(name: str) -> BaseSource:
    """获取站点实例（单例模式）。"""
    if name not in _REGISTRY:
        raise ValueError(f"未知资源站: {name!r}，可选: {', '.join(SOURCE_NAMES)}")
    with _INSTANCES_LOCK:
        if name not in _INSTANCES:
            _INSTANCES[name] = _REGISTRY[name]()
        return _INSTANCES[name]


def all_sources() -> list[BaseSource]:
    """按优先级返回所有站点实例。"""
    return [get_source(n) for n in SOURCE_PRIORITY]
