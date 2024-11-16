from os import makedirs, remove, removedirs
from pathlib import Path
from aiofiles import open as aopen
from nonebot.adapters.onebot.v11 import MessageSegment, Message
from httpx import AsyncClient
from nonebot_plugin_orm import get_session
from sqlalchemy.future import select
from sqlalchemy import delete
from .model import GroupImageBanInfo

from nonebot import logger
from common import generate_random_string
import nonebot_plugin_localstore as store


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
            infos = (await session.execute(condition)).scalars().all()
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
                ext_name = str(img.data.get("file")).split(".")[-1]
                img_name = generate_random_string(16) + "." + ext_name
                url = img.data.get("url")
                size = img.data.get("file_size", img_name)
                # 下载图片到本地
                response = await client.get(str(url))
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

    async def remove_ban_image(self, imgs: list[MessageSegment]) -> list[MessageSegment]:
        """删除禁言图片

        Args:
            img (list[MessageSegment]): 删除的禁言图片
        """
        if not self.img_store.exists():
            makedirs(self.img_store.as_posix())
        fail_list: list[MessageSegment] = []
        for img in imgs:
            # 添加文件大小到缓冲区
            file_size = img.data.get("file_size", img.data.get("file"))
            # 删除本地图片
            file_name = self.cache.get(file_size)
            logger.debug(f"file_name: {file_name}")
            # 图片不存在，则进行本地图片删除
            if file_name is None:
                fail_list.append(img)
                continue
            file = self.img_store.joinpath(file_name)
            try:
                remove(file)
            except FileNotFoundError:
                fail_list.append(img)
                logger.error(f"文件 {file} 不存在。")
        # 删除数据库对应信息
        sizes = set([img.data.get("file_size") for img in imgs])
        session = get_session()
        async with session.begin():
            await session.execute(delete(GroupImageBanInfo).where(GroupImageBanInfo.file_size.in_(sizes)))
        await session.commit()
        await self.load()
        return fail_list

    async def clear_ban_image(self):
        # 删除文件
        for _, name in self.cache.items():
            file = self.img_store.joinpath(name)
            try:
                remove(file)
            except FileNotFoundError:
                logger.error(f"文件 {file} 不存在。")
        if self.img_store.exists():
            removedirs(self.img_store.as_posix())
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
