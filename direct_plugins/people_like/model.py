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
    ext_name: Mapped[str]
    """图片扩展名"""
    url: Mapped[str]
    """图片url"""
    file_uri: Mapped[str]
    """图片文件uri"""
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