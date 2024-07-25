from nonebot.plugin import PluginMetadata

__plugin_meta__ = PluginMetadata(
    name="ban_image",
    description="",
    usage="",    
    extra={
        'menu_data': [
            {
                'func': '别发了',
                'trigger_method': 'on_msg',
                'trigger_condition': '别发了',
                'brief_des': '拉黑图片',
                'detail_des': '管理员对图片消息回复“别发了”'
            },
            {
                'func': '随便发',
                'trigger_method': 'on_msg',
                'trigger_condition': '随便发',
                'brief_des': '取消拉黑图片',
                'detail_des': '管理员对图片消息回复“随便发”'
            },
            {
                'func': '让我看看什么不能发',
                'trigger_method': 'on_fullmatch',
                'trigger_condition': '让我看看什么不能发',
                'brief_des': '查询本群拉黑图片',
                'detail_des': '发送“让我看看什么不能发”'
            },
            {
                'func': '都可以发',
                'trigger_method': 'on_fullmatch',
                'trigger_condition': '都可以发',
                'brief_des': '清空本群拉黑图片',
                'detail_des': '管理员发送“都可以发”'
            }
        ],
        'menu_template': 'default'
    }
)
