from nonebot_plugin_orm import Model
from sqlalchemy.orm import Mapped, mapped_column


class ScheduleBanJob(Model):
    """群组定时禁言信息"""

    job_id: Mapped[str] = mapped_column(primary_key=True)
    """任务id"""
    group_id: Mapped[int] = mapped_column(index=True)
    """群组id"""
    user_id: Mapped[int]
    """用户id"""
    period: Mapped[int]
    """单次禁言时间"""
    start_hour: Mapped[int]
    """禁言开始时刻"""
    start_minute: Mapped[int]
    """禁言开始分刻"""
    once: Mapped[bool]
    """是否为一次性任务"""

