"""懒建单例的唯一实现：double-checked locking + `threading.RLock`（AGENTS.md §3）。

**为什么要有这一份**：仓内 200 多个 `get_xxx()` 形态的懒建单例各写各的，实测有 74 处
`if _x is None: _x = X()` **完全不带锁**——两个线程同时进判空就会各建一份，后写的赢，
先建的那份带着已注册的回调/已打开的连接被静默丢弃。这类故障在单线程测试里永远不显形。

**存储位置刻意不变**：被缓存的值仍写回**本模块的那个全局名**（而不是藏进装饰器闭包），
所以既有的 `mod._x_instance = None` 复位路径（测试与关停钩子都在用）继续成立，
本模块也不额外持有引用。
"""

import functools
import threading
from typing import Any, Callable, Optional

__all__ = ["lazySingleton"]


def lazySingleton(attrName: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """把"判空即建"的 getter 变成 DCL + RLock 的单例入口。

    被装饰函数的**函数体即构造过程**：只在缓存未命中时执行，入参原样透传，
    返回值写入 `attrName` 所指的本模块全局。语义与手写
    `if g is None: g = build(...); return g` 逐字相同，只是判空被锁护住。

    Raises:
        ValueError: 本模块不存在 `attrName` 这个全局。写错名字会让缓存**永远不命中**、
            每次调用都新建一份——那正是本模块要消灭的故障，所以在装饰期就拒绝，
            而不是留到运行时静默退化。
    """

    def decorator(builder: Callable[..., Any]) -> Callable[..., Any]:
        store = builder.__globals__
        if attrName not in store:
            raise ValueError(
                f"lazySingleton: 模块 {store.get('__name__', '?')} 里没有全局 {attrName!r}"
                f"——缓存名写错会让单例每次重建，请在模块级声明 `{attrName} = None`"
            )
        # RLock：构造过程可能回调到同一入口（AGENTS.md §3 的 re-entrant 要求）
        lock = threading.RLock()

        @functools.wraps(builder)
        def getInstance(*args: Any, **kwargs: Any) -> Any:
            cached = store.get(attrName)
            if cached is not None:
                return cached
            with lock:
                cached = store.get(attrName)
                if cached is not None:
                    return cached
                created = builder(*args, **kwargs)
                store[attrName] = created
                return created

        return getInstance

    return decorator
