from os import makedirs, remove
from pathlib import Path
import time
from typing import Any, Optional
from aiofiles import open as aopen
from nonebot.adapters.onebot.v11 import MessageSegment, Message
from httpx import AsyncClient
from nonebot_plugin_orm import get_session
from sqlalchemy.future import select
from sqlalchemy import delete
from .model import GroupImageBanInfo

from nonebot import logger, require

require("nonebot_plugin_localstore")

import nonebot_plugin_localstore as store  # noqa: E402


class BanImage:
    def __init__(self, group_id: int) -> None:
        self.group_id = group_id
        """群组id"""
        self.img_store: Path = store.get_data_dir("ban_image").joinpath(f"img_store_{group_id}")
        """图片存储位置"""

    async def load(self) -> "BanImage":
        session = get_session()
        async with session.begin():
            # 过滤指定群组所有违禁图片信息
            condition = select(GroupImageBanInfo).filter_by(group_id=self.group_id)
            infos: list[GroupImageBanInfo] = (await session.execute(condition)).scalars().all()
            self.cache: dict[str, str] = {info.file_size: info.img_name for info in infos}
            """存储图片尺寸及图片名称"""
            logger.debug(f"cache: {self.cache}")
        return self

    async def add_ban_image(self, imgs: list[MessageSegment]):
        """添加禁言图片

        Args:
            img (list[MessageSegment]): 追加的禁言图片
        """
        if not self.img_store.exists():
            makedirs(self.img_store.as_posix())
        gibis = []
        async with AsyncClient() as client:
            for img in imgs:
                img_name = img.data.get("file")
                url = img.data.get("url")
                size = img.data.get("file_size", img_name)
                # 下载图片到本地
                response = await client.get(url)
                async with aopen(self.img_store.joinpath(img_name), "wb") as f:
                    await f.write(response.content)
                # 构造数据
                gibi = GroupImageBanInfo(group_id=self.group_id, file_size=size, img_name=img_name)
                gibis.append(gibi)
        # 保存到数据库中
        session = get_session()
        async with session.begin():
            session.add_all(gibis)
        await session.commit()
        await self.load()

    async def remove_ban_image(self, imgs: list[MessageSegment]):
        """删除禁言图片

        Args:
            img (list[MessageSegment]): 删除的禁言图片
        """
        if not self.img_store.exists():
            makedirs(self.img_store.as_posix())
        for img in imgs:
            # 添加文件大小到缓冲区
            file_size = img.data.get("file_size", img.data.get("file"))
            # 删除本地图片
            file_name = self.cache.get(file_size)
            logger.debug(f"file_name: {file_name}")
            file = self.img_store.joinpath(file_name)
            try:
                remove(file)
            except FileNotFoundError:
                logger.error(f"文件 {file} 不存在。")
        # 删除数据库对应信息
        sizes = set([img.data.get("file_size") for img in imgs])
        session = get_session()
        async with session.begin():
            await session.execute(delete(GroupImageBanInfo).where(GroupImageBanInfo.file_size.in_(sizes)))
        await session.commit()
        await self.load()

    async def clear_ban_image(self):
        # 删除文件
        for _, name in self.cache.items():
            file = self.img_store.joinpath(name)
            try:
                remove(file)
            except FileNotFoundError:
                logger.error(f"文件 {file} 不存在。")
        # 删表数据
        session = get_session()
        async with session.begin():
            await session.execute(delete(GroupImageBanInfo).where(GroupImageBanInfo.group_id == self.group_id))
        await session.commit()
        await self.load()

    async def list_ban_image(self, name: str, uid: int) -> list:
        """展示已被禁止的图片

        Args:
            name(str): bot昵称
            uid(int): bot账号

        Returns:
            list: 消息
        """
        msg = []
        for size, name in self.cache.items():
            logger.debug(f"{size}: {name}")
            async with aopen(self.img_store.joinpath(name), "rb") as f:
                content = await f.read()
                ms1 = MessageSegment.text(text=size)
                ms2 = MessageSegment.image(file=content)
                msg.append(
                    {
                        "type": "node",
                        "data": {
                            "name": name,
                            "uin": uid,
                            "content": Message([ms1, ms2]),
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
        return img.data.get("file_size", img.data.get("file")) in self.cache.keys()


class ExpirableDict:
    def __init__(self, name: str) -> None:
        self.name = name
        self.__data: dict[str, Any] = {}
        self.__expiry: dict[str, int] = {}

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        self.__data[key] = value
        # 如果有设置过期时间，则更新过期时间
        if ttl is not None:
            expiry_time = int(time.time()) + ttl
            self.__expiry[key] = expiry_time

    def get(self, key: str) -> Optional[Any]:
        # 如果没有设置过期时间，则直接返回值
        if self.__expiry.get(key) is None:
            return self.__data.get(key)
        # 如果有过期时间，且已过期，则删除
        if int(time.time()) > self.__expiry[key]:
            del self.__data[key]
            del self.__expiry[key]
        return self.__data.get(key)

    def delete(self, key: str) -> None:
        if key in self.__data:
            del self.__data[key]
        if key in self.__expiry:
            del self.__expiry[key]

    def ttl(self, key: str) -> int: 
        # 键对应的值不存在
        if self.__data.get(key) is None:
            return -2
        # 键没有设置过期时间
        if (expiry := self.__expiry.get(key)) is None:
            return -1
        # 键已过期
        if (ttl := expiry - int(time.time())) <= 0:
            return 0
        return ttl

    def exists(self, key: str) -> bool:
        return self.get(key) is not None

    def __add__(self, other: "ExpirableDict") -> "ExpirableDict":
        result = ExpirableDict(name=self.name)
        result.__data = {k: v.copy() for k, v in self.__data.items()}
        result.__expiry = {k: v.copy() for k, v in self.__expiry.items()}

        for key, value in other.__data.items():
            if key not in result.__data:
                result.__data[key] = value

        for key, value in other.__expiry.items():
            if key not in result.__expiry:
                result.__expiry[key] = value

        return result

    def __sub__(self, other: "ExpirableDict") -> "ExpirableDict":
        result = ExpirableDict(name=self.name)
        result.__data = {k: v.copy() for k, v in self.__data.items()}
        result.__expiry = {k: v.copy() for k, v in self.__expiry.items()}

        for key, _ in other.__data.items():
            if key in result.__data:
                del result.__data[key]
            if key in result.__expiry:
                del result.__expiry[key]

        return result

    def __repr__(self) -> str:
        res = f"{ExpirableDict.__name__}: {self.name}"
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
