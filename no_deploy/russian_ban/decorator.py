from functools import wraps
from typing import Any, Awaitable, Callable, Optional, TypeVar
from nonebot import logger
from nonebot.adapters.onebot.v11 import GroupMessageEvent

T = TypeVar("T")
T_Wrapper = Callable[..., Awaitable[T]]
T_Decorator = Callable[..., T]


def switch_depend(*, dependOn: list[Callable[..., bool]], ignoreIds: set[int]) -> T_Decorator[T_Wrapper[None]]:
    """装饰 random_mute 方法，使某些特殊情况下的事件不被处理

    Args:
        dependOn (list): 依赖的开关项，每一项为返回 bool 的函数
        ignoreIds (set[int]): 忽略的 user_id
    Returns:
        Callable[[F], F]: 处理后的方法
    """

    def decorator(func: T_Wrapper[None]) -> T_Wrapper[None]:
        """装饰器本体

        Args:
            func (F): 原方法

        Returns:
            F: 处理后的方法
        """

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> None:
            """装饰器处理方法

            Returns:
                Any: 方法执行结果
            """
            event: Optional[GroupMessageEvent] = kwargs.get("event", None)
            if event and event.user_id in ignoreIds:
                logger.debug(f"忽略用户 {event.user_id} 的操作")
                return
            if any(not item(*args, **kwargs) for item in dependOn):
                logger.debug("忽略操作")
                return
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def mute_sb_stop_runpreprocessor(*, ignoreIds: set[int]) -> T_Decorator[T_Wrapper[None]]:
    """装饰 mute_sb 处理函数，在其处理函数结束运行时将 ignoreIds 中对应的 user_id 移除

    Args:
        ignoreIds (set[int]): 忽略的 user_id

    Returns:
        Callable[[F], F]: 装饰后的新函数
    """

    def decorator(func: T_Wrapper[None]) -> T_Wrapper[None]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> None:
            event: Optional[GroupMessageEvent] = kwargs.get("event", None)
            if event:
                ignoreIds.add(event.user_id)
                logger.debug(f"{ignoreIds} will append {event.user_id}")
                try:
                    res = await func(*args, **kwargs)
                finally:
                    ignoreIds.remove(event.user_id)
                    logger.debug(f"移除用户 {event.user_id} 的操作, 当前忽略列表: {ignoreIds}")
                return res

        return wrapper

    return decorator


def negate_return_value(func: Callable[..., bool]) -> Callable[..., bool]:
    """将返回值类型为bool的函数调用返回值取反

    Args:
        func (Callable[..., bool]): 原函数
    """

    def wrapper(*args, **kwargs) -> bool:
        print(args, kwargs)
        result = func(*args, **kwargs)
        return not result

    return wrapper
