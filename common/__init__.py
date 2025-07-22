from time import sleep
from typing import Optional, Callable
import random
import string
import functools
import asyncio


def generate_random_string(length: int) -> str:
    """生成指定长度的随机字符串

    Args:
        length (int): 长度

    Returns:
        str: 结果
    """
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def retry_on_exception(max_retries: int = 3, sleep_time: int = 0, exceptions=(Exception,), on_exception: Optional[Callable] = None):
    """
    装饰器：指定重试次数，异常时重试，次数用完抛异常
    :param max_retries: 最大重试次数
    :param sleep_time: 重试间隔时间，单位秒
    :param exceptions: 需要捕获的异常类型
    :param on_exception: 捕获异常时额外执行的函数，签名为 func(e, attempt) e 是异常对象，attempt 是当前尝试次数
    """

    def decorator(func):
        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                for attempt in range(max_retries):
                    try:
                        return await func(*args, **kwargs)
                    except exceptions as e:
                        if on_exception:
                            if asyncio.iscoroutinefunction(on_exception):
                                await on_exception(e, attempt)
                            else:
                                on_exception(e, attempt)
                            await asyncio.sleep(sleep_time)
                        if attempt == max_retries - 1:
                            raise

            return async_wrapper
        else:

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                for attempt in range(max_retries):
                    try:
                        return func(*args, **kwargs)
                    except exceptions as e:
                        if on_exception:
                            if asyncio.iscoroutinefunction(on_exception):
                                asyncio.run(on_exception(e, attempt))
                            else:
                                on_exception(e, attempt)
                            sleep(sleep_time)
                        if attempt == max_retries - 1:
                            raise

            return sync_wrapper

    return decorator
