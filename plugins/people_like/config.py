from typing import Optional
from pydantic import BaseModel
from nonebot import get_plugin_config


class Config(BaseModel):
    """Plugin Config Here"""
    reply_probability: float = 0.05
    """回复概率"""
    repeat_probability: float = 0.01
    """复读概率"""
    context_size: int = 20
    """上下文长度"""
    at_context_max_size: int = 20
    """被@时的最大上下文长度"""
    msg_send_interval_per_10: int = 1
    """每超过 10 个字符，回复间隔增加 1 s"""
    reply_msg_max_length: int = 50
    """单条消息最大长度"""
    gemini_key: Optional[str]
    """Gemini API Key"""


plugin_config = get_plugin_config(Config)
