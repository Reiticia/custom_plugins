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
                'trigger_condition': '<s>mute sb</s>',
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
                'trigger_condition': 'mute voting $st',
                'brief_des': '禁言投票',
                'detail_des': '触发命令后，每个群成员可以通过@某人进行投票，\n票数达到指定数量后，bot会自动禁言该成员'
            },
            {
                'func': '预约禁言',
                'trigger_method': 'on_cmd',
                'trigger_condition': 'mute schedule @$sb $st at $st',
                'brief_des': '预约禁言',
                'detail_des': '触发命令后，将在指定时间点禁言该用户指定时间，只执行一次，at后可只跟时刻，如10，或时分，如10:30'
            },
            {
                'func': '查看预约禁言',
                'trigger_method': 'on_cmd',
                'trigger_condition': 'list schedule',
                'brief_des': '查看预约禁言',
                'detail_des': '查看预约禁言列表'
            },
            {
                'func': '移除预约禁言',
                'trigger_method': 'on_cmd',
                'trigger_condition': 'remove schedule $id...',
                'brief_des': '移除预约禁言',
                'detail_des': '移除指定id的预约禁言'
            },
            {
                'func': '模拟禁言',
                'trigger_method': 'on_cmd',
                'trigger_condition': 'mock mute $id',
                'brief_des': '模拟禁言',
                'detail_des': '将指定用户进行模拟禁言（每次发言将被撤回）'
            },
            {
                'func': '移除模拟禁言',
                'trigger_method': 'on_cmd',
                'trigger_condition': 'mock mute delete $id',
                'brief_des': '移除模拟禁言',
                'detail_des': '移除指定id的模拟禁言'
            },
        ],
        'menu_template': 'default'
    }
)
