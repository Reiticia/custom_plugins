from typing import Any, Awaitable, Callable, TypeVar
import functools

F = TypeVar('F', bound=Callable[..., Awaitable[None]])


def switch_depend(*, dependOn:list[Callable[..., bool]]) -> Callable[[F], F]:
    """装饰器名称

    Args:
        dependOn (list): 装饰器参数，方法是否执行的依赖项

    Returns:
        Callable[[F], F]: 处理后的方法
    """
    def decorator(func: F) -> F:
        """装饰器本体

        Args:
            func (F): 原方法

        Returns:
            F: 处理后的方法
        """
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> None:
            """装饰器处理方法

            Returns:
                Any: 方法执行结果
            """
            for item in dependOn:
                if not item():
                    return
            else:
                return await func(*args, **kwargs)
        return wrapper
    return decorator
