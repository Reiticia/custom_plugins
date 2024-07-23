from os import makedirs, remove
from pathlib import Path
import time
from typing import Any, Optional
from aiofiles import open as aopen
from json import loads, dumps
from nonebot.adapters.onebot.v11 import MessageSegment, Message
from httpx import AsyncClient

from nonebot import require

require("nonebot_plugin_localstore")

import nonebot_plugin_localstore as store  # noqa: E402


class BanImage:
    def __init__(self, data_store: Path = store.get_data_file("ban_image", "ban_iamge_size.json")) -> None:
        self.data_store = data_store
        """数据存储位置
        """
        if data_store.exists():
            self.sizes = set(loads(t)) if (t := data_store.read_text()) else set()
            """不允许发送的图片特征：图片大小
            """
        else:
            self.sizes = set()
        self.img_store: Path = store.get_data_dir("ban_image").joinpath("img_store")

    async def save(self):
        """保存禁言图片数据"""
        async with aopen(self.data_store, mode="w") as fp:
            await fp.write(dumps(list(self.sizes), indent=4))

    async def add_ban_image(self, imgs: list[MessageSegment]):
        """添加禁言图片

        Args:
            img (list[MessageSegment]): 追加的禁言图片
        """
        if not self.img_store.exists():
            makedirs(self.img_store.as_posix())
        async with AsyncClient() as client:
            for img in imgs:
                # 添加文件大小到缓冲区
                self.sizes.add(int(size := img.data.get("file_size")))
                # 下载图片到本地
                url = img.data.get("url")
                response = await client.get(url)
                async with aopen(self.img_store.joinpath(str(size)), "wb") as f:
                    await f.write(response.content)

    async def remove_ban_image(self, imgs: list[MessageSegment]):
        """删除禁言图片

        Args:
            img (list[MessageSegment]): 删除的禁言图片
        """
        if not self.img_store.exists():
            makedirs(self.img_store.as_posix())
        for img in imgs:
            # 添加文件大小到缓冲区
            self.sizes.remove(int(size := img.data.get("file_size")))
            # 删除本地图片
            file = self.img_store.joinpath(str(size))
            try:
                remove(file)
            except FileNotFoundError:
                print(f"文件 {file} 不存在。")

    async def list_ban_image(self, name: str, uid: int) -> list:
        """展示已被禁止的图片

        Args:
            name(str): bot昵称
            uid(int): bot账号

        Returns:
            list: 消息
        """
        msg = []
        for size in self.sizes:
            async with aopen(self.img_store.joinpath(str(size)), "rb") as f:
                content = await f.read()
                ms = MessageSegment.image(file=content)
                msg.append(
                    {
                        "type": "node",
                        "data": {
                            "name": name,
                            "uin": uid,
                            "content": Message(ms),
                        },
                    }
                )
        return msg

    def check_image_equals(self, img: MessageSegment) -> bool:
        """检测是否匹配 TODO 更好的匹配策略

        Args:
            img (MessageSegment): 图片消息段

        Return:
            bool: 是否匹配
        """
        return int(img.data.get("file_size")) in self.sizes


class ExpirableDict:
    def __init__(self, name: str) -> None:
        self.name = name
        self.data: dict[str, Any] = {}
        self.expiry: dict[str, int] = {}

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        self.data[key] = value
        # 如果有设置过期时间，则添加过期时间
        if ttl is not None:
            expiry_time = int(time.time()) + ttl
            self.expiry[key] = expiry_time

    def get(self, key: str) -> Optional[Any]:
        # 如果没有设置过期时间，则直接返回值
        if self.expiry.get(key) is None:
            return self.data.get(key)
        # 如果有过期时间，且已过期，则删除
        if int(time.time()) > self.expiry[key]:
            del self.data[key]
            del self.expiry[key]
        return self.data.get(key)

    def delete(self, key: str) -> None:
        if key in self.data:
            del self.data[key]
        if key in self.expiry:
            del self.expiry[key]

    def exists(self, key: str) -> bool:
        return self.get(key) is not None

    def __add__(self, other: "ExpirableDict") -> "ExpirableDict":
        result = ExpirableDict(name=self.name)
        result.data = {k: v.copy() for k, v in self.data.items()}
        result.expiry = {k: v.copy() for k, v in self.expiry.items()}

        for key, value in other.data.items():
            if key not in result.data:
                result.data[key] = value

        for key, value in other.expiry.items():
            if key not in result.expiry:
                result.expiry[key] = value

        return result

    def __sub__(self, other: "ExpirableDict") -> "ExpirableDict":
        result = ExpirableDict(name=self.name)
        result.data = {k: v.copy() for k, v in self.data.items()}
        result.expiry = {k: v.copy() for k, v in self.expiry.items()}

        for key, _ in other.data.items():
            if key in result.data:
                del result.data[key]
            if key in result.expiry:
                del result.expiry[key]

        return result

    def __repr__(self) -> str:
        res = f"{ExpirableDict.__name__}: {self.name}"
        del_key = []
        for key, value in self.data.items():
            # 过期时间为None，表示永不过期
            if (expiry := self.expiry.get(key)) is None:
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
