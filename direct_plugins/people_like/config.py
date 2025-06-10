from typing import Optional
from pydantic import BaseModel, Field
from nonebot import get_plugin_config



class MilvusConfig(BaseModel):
    """Milvus 配置"""
    username: str = ""
    """用户名
    """
    password: str = ""
    """密码
    """
    uri: str = "http://localhost:19530"
    """连接地址
    """


class Config(BaseModel):
    """Plugin Config Here"""

    reply_probability: float = 0.05
    """回复概率"""
    repeat_probability: float = 0.01
    """复读概率"""
    context_size: int = 40
    """上下文长度"""
    one_word_max_used_time_of_second: int = 1
    """一个字最多花费多少时间"""
    image_analyze: bool = True
    """是否开启图片分析"""
    gemini_key: Optional[str]
    """Gemini API Key"""
    gemini_model: str = "gemini-2.0-flash"
    """Gemini 模型"""
    query_len: int = 10
    """查询长度"""
    search_len: int = 10
    """搜索长度"""
    milvus: MilvusConfig = Field(default_factory=MilvusConfig)
    """Milvus 配置"""


plugin_config = get_plugin_config(Config)
