from nonebot_plugin_uninfo.permission import ADMIN, OWNER
from nonebot.permission import SUPERUSER

admin_permission = SUPERUSER | ADMIN() | OWNER()
"""管理权限
"""

owner_permission = SUPERUSER | OWNER()
"""群主权限"""
