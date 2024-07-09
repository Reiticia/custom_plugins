from nonebot.plugin import PluginMetadata
from .config import Config

__plugin_meta__ = PluginMetadata(
    name="russian_ban",
    description="花式禁言",
    usage="",
    config=Config,
    extra={
        'menu_data': [
            {
                'func': '清除',
                'trigger_method': 'on_cmd',
                'trigger_condition': 'mute clear',
                'brief_des': '清除禁言列表',
                'detail_des': '清除禁言列表'
            },
            {
                'func': '查询',
                'trigger_method': 'on_cmd',
                'trigger_condition': 'mute query',
                'brief_des': '查询禁言次数',
                'detail_des': '查询禁言次数'
            },
            {
                'func': '历史',
                'trigger_method': 'on_cmd',
                'trigger_condition': 'mute history',
                'brief_des': '查询禁言历史',
                'detail_des': '查询禁言历史'
            },
            {
                'func': '禁言某人',
                'trigger_method': 'on_cmd',
                'trigger_condition': 'mute sb',
                'brief_des': '禁言某人',
                'detail_des': '触发命令后，需要输入QQ号或者@指定成员，然后输入禁言时长'
            },
            {
                'func': '禁言某人',
                'trigger_method': 'on_cmd',
                'trigger_condition': 'mute @$sb $st',
                'brief_des': '禁言某人',
                'detail_des': '触发命令后，需要输入QQ号或者@指定成员，然后输入禁言时长'
            },
            {
                'func': '禁言投票',
                'trigger_method': 'on_cmd',
                'trigger_condition': '@bot mute voting $st',
                'brief_des': '禁言投票',
                'detail_des': '触发命令后，每个群成员可以通过@某人进行投票，\n票数达到指定数量后，bot会自动禁言该成员'
            },
        ],
        'menu_template': 'default'
    }
)
