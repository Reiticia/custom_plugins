from nonebot_plugin_orm import Model
from sqlalchemy.orm import Mapped, mapped_column



class GroupImageBanInfo(Model):
    """群组违禁图片信息"""
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    """主键"""
    group_id: Mapped[int] = mapped_column(index=True)
    """群组id"""
    file_size: Mapped[str]
    """文件大小"""
    img_name: Mapped[str]
    """文件名称"""