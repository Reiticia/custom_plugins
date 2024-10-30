import time
from typing import Optional, Generic, TypeVar

# 创建类型变量
K = TypeVar("K")
V = TypeVar("V")


class ExpirableDict(Generic[K, V]):
    def __init__(self, name: str) -> None:
        self.name = name
        self.__data: dict[K, V] = {}
        self.__expiry: dict[K, int] = {}

    def set(self, key: K, value: V, ttl: Optional[int] = None) -> None:
        self.__data[key] = value
        # 如果有设置过期时间，则更新过期时间
        if ttl is not None:
            expiry_time = int(time.time()) + ttl
            self.__expiry[key] = expiry_time

    def get(self, key: K) -> Optional[V]:
        # 如果没有设置过期时间，则直接返回值
        if self.__expiry.get(key) is None:
            return self.__data.get(key)
        # 如果有过期时间，且已过期，则删除
        if int(time.time()) > self.__expiry[key]:
            del self.__data[key]
            del self.__expiry[key]
        return self.__data.get(key)

    def delete(self, key: K) -> None:
        if key in self.__data:
            del self.__data[key]
        if key in self.__expiry:
            del self.__expiry[key]

    def ttl(self, key: K) -> int:
        # 键对应的值不存在
        if self.__data.get(key) is None:
            return -2
        # 键没有设置过期时间
        if (expiry := self.__expiry.get(key)) is None:
            return -1
        # 键已过期
        if (ttl := expiry - int(time.time())) <= 0:
            self.delete(key)  # 同时删除键
            return 0
        return ttl

    def exists(self, key: K) -> bool:
        return self.get(key) is not None

    def __add__(self, other: "ExpirableDict[K,V]") -> "ExpirableDict[K,V]":
        result = ExpirableDict[K, V](name=self.name)
        result.__data = {k: v.copy() for k, v in self.__data.items()}
        result.__expiry = {k: v.copy() for k, v in self.__expiry.items()}

        for key, value in other.__data.items():
            if key not in result.__data:
                result.__data[key] = value

        for key, value in other.__expiry.items():
            if key not in result.__expiry:
                result.__expiry[key] = value

        return result

    def __sub__(self, other: "ExpirableDict[K,V]") -> "ExpirableDict[K,V]":
        result = ExpirableDict[K, V](name=self.name)
        result.__data = {k: v.copy() for k, v in self.__data.items()}
        result.__expiry = {k: v.copy() for k, v in self.__expiry.items()}

        for key, _ in other.__data.items():
            if key in result.__data:
                del result.__data[key]
            if key in result.__expiry:
                del result.__expiry[key]

        return result

    def __repr__(self) -> str:
        res = f"{ExpirableDict[K,V].__name__}: {self.name}"
        del_key = []
        for key, value in self.__data.items():
            # 过期时间为None，表示永不过期
            if (expiry := self.__expiry.get(key)) is None:
                ttl = -1
            else:
                # 如果过期
                if (ttl := expiry - int(time.time())) <= 0:
                    del_key.append(key)
                    continue
            line = f"\n{key}\t{value}\t{ttl}"
            res += line

        for key in del_key:
            self.delete(key)

        return res
