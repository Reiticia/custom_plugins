from pathlib import Path
from nonebot import get_plugin_config
from pydantic import BaseModel, Field

base_path = Path("/etc/ShellCrash/yamls")


class CrashConfig(BaseModel):
    rules_path: str = str(base_path / "rules.yaml")
    """自定义规则配置文件路径
    """
    proxy_groups_path: str = str(base_path / "proxy-groups.yaml")
    """自定义代理组配置文件路径
    """
    config_path: str = str(base_path / "config.yaml")
    """原始代理配置文件路径
    """


class Config(BaseModel):
    """Plugin Config Here"""

    shellcrash: CrashConfig = Field(default_factory=CrashConfig)


plugin_config = get_plugin_config(Config).shellcrash
