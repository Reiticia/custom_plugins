# 数据库实体

from nonebot_plugin_orm import Model
from sqlalchemy.orm import Mapped, mapped_column

class ImageSender(Model):
    """图片发送者消息"""

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    """主键id"""
    group_id: Mapped[int] = mapped_column(nullable=True)
    """群组id"""
    user_id: Mapped[int] = mapped_column(nullable=True)
    """用户id"""
    name: Mapped[str] = mapped_column(index=True)
    """图片名称"""
    summary: Mapped[str] = mapped_column(nullable=True)
    """图片简介"""
    ext_name: Mapped[str]
    """图片扩展名"""
    url: Mapped[str]
    """图片url"""
    file_uri: Mapped[str]
    """图片文件uri"""
    mime_type: Mapped[str] = mapped_column(nullable=True)
    """图片mime类型"""
    remote_file_name: Mapped[str] = mapped_column(nullable=True)
    """图片远程文件名"""
    file_size: Mapped[int] = mapped_column(nullable=True)
    """动画表情文件大小"""
    key: Mapped[str] = mapped_column(nullable=True)
    """商店表情key"""
    emoji_id: Mapped[str] = mapped_column(nullable=True)
    """商店表情emoji_id"""
    emoji_package_id: Mapped[str] = mapped_column(nullable=True)
    """商店表情包id"""
    create_time: Mapped[int]
    """创建时间"""
    update_time: Mapped[int]
    """更新时间"""

class GroupMsg(Model):
    """记录消息数据结构"""
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)  # 自增主键
    message_id: Mapped[int] = mapped_column(nullable=True)  # 如果缺少 message_id 则为通知消息
    group_id: Mapped[int]
    user_id: Mapped[int]
    self_msg: Mapped[bool]  # 是否为自己的消息
    to_me: Mapped[bool]  # 是否为提及自己的消息
    index: Mapped[int]
    nick_name: Mapped[str]
    content: Mapped[str]
    file_id: Mapped[str] = mapped_column(nullable=True)
    time: Mapped[int]  # 时间戳

class GroupMemberImpression(Model):
    """群成员印象"""
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    group_id: Mapped[int]
    user_id: Mapped[int]
    impression: Mapped[str] = mapped_column(nullable=True)
    create_time: Mapped[int]
    update_time: Mapped[int]