from pydantic import BaseModel
from nonebot import get_plugin_config


class Config(BaseModel):
    """Plugin Config Here"""
    enable_handle_self: bool = False  # 是否开启处理自身消息功能
    self_report_tome: bool = False  # 是否将私聊消息设置为tome（不将私聊消息设置为tome可能不会响应自身私聊消息）
    replay_time: int = 1  # 间隔多少s重新构造事件发送给bot

plugin_config = get_plugin_config(Config)