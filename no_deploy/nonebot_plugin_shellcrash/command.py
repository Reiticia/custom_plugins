from typing import Any, cast
from nonebot import logger, get_driver
from nonebot.permission import SUPERUSER
from nonebot_plugin_alconna import Alconna, AlconnaMatches, Args, Arparma, Option, Subcommand, UniMessage, on_alconna
from nonebot_plugin_htmlrender import md_to_pic
import ruamel.yaml

from .model import ProxyGroup, ProxyGroupType, RuleType, SingleRule
from .config import plugin_config
from nonebot_plugin_waiter import suggest, prompt

driver = get_driver()

config_proxy_groups = list[ProxyGroup]()
custom_proxy_groups = list[ProxyGroup]()
custom_rules = list[SingleRule]()
default_policy: set[str] = {"DIRECT", "REJECT"}

yaml = ruamel.yaml.YAML()


@driver.on_startup
async def _():
    global yaml, config_proxy_groups, custom_proxy_groups, custom_rules
    yaml.indent(mapping=2, sequence=4, offset=2)
    # 读取配置文件，建立生成配置代理组
    try:
        with open(plugin_config.config_path, "r", encoding="utf-8") as file:
            data = yaml.load(file)
            data_typing = cast(dict[str, Any], data)
            for proxy_group in data_typing["proxy-groups"]:
                group = ProxyGroup(
                    name=proxy_group["name"],
                    type=ProxyGroupType.value_of(proxy_group["type"]),
                    proxies=proxy_group["proxies"],
                )
                config_proxy_groups.append(group)
    except ruamel.yaml.YAMLError as e:
        print(f"Error loading YAML file: {e}")
        return None
    # 读取自定义代理组
    try:
        with open(plugin_config.proxy_groups_path, "r", encoding="utf-8") as file:
            data = yaml.load(file)
            data_typing = cast(list[Any], data)
            for proxy_group in data_typing:
                group = ProxyGroup(
                    name=proxy_group["name"],
                    type=ProxyGroupType.value_of(proxy_group["type"]),
                    proxies=proxy_group["proxies"],
                )
                custom_proxy_groups.append(group)
    except ruamel.yaml.YAMLError as e:
        print(f"Error loading YAML file: {e}")
        return None
    # 读取自定义规则
    try:
        with open(plugin_config.rules_path, "r", encoding="utf-8") as file:
            data: list[str] = yaml.load(file)
            for rule in data:
                s = rule.split(",")
                single_rule = SingleRule(
                    rule_type=RuleType.value_of(s[0]), rule_parameter=s[1], rule_policy=s[2], no_resolve=len(s) > 3
                )
                custom_rules.append(single_rule)
    except ruamel.yaml.YAMLError as e:
        print(f"Error loading YAML file: {e}")
        return None

    # logger.debug(config_proxy_groups)
    # logger.debug(custom_proxy_groups)
    # logger.debug(custom_rules)


clash_setting = on_alconna(
    Alconna(
        "clash",
        Subcommand(
            "add",
            Option("-r|--rule", Args["rule", str]),
            Option("-g|--group", Args["group", str]),
        ),
        Subcommand(
            "remove",
            Option("-r|--rule", Args["rule", str]),
            Option("-g|--group", Args["group", str]),
        ),
        Subcommand(
            "list",
            Option("-r|--rule"),
            Option("-g|--group"),
        ),
    ),
    permission=SUPERUSER,
)


@clash_setting.assign("add")
async def add_group_or_rule(args: Arparma = AlconnaMatches()):
    """添加自定义组或规则

    Args:
        args (Arparma, optional): _description_. Defaults to AlconnaMatches().
    """
    global config_proxy_groups, custom_proxy_groups, custom_rules
    rule_name = args.query[str]("rule")
    group_name = args.query[str]("group")
    suggest_rule_policy = list(
        {g.name for g in config_proxy_groups} | {g.name for g in custom_proxy_groups} | default_policy
    )
    logger.debug(suggest_rule_policy)
    if rule_name:
        suggest_value = RuleType.values()
        rule_type = await suggest("请输入规则类型", expect=suggest_value)
        rule_parameter = await prompt("请输入规则参数")
        rule_policy = await suggest("请输入规则策略", expect=suggest_rule_policy)
        is_no_resolve = await suggest("no-resolve?", expect=["y", "n"])
        no_resolve = True if is_no_resolve == "y" else False
        if rule_type is not None and rule_parameter is not None and rule_policy is not None:
            single_rule = SingleRule(
                rule_type=RuleType.value_of(str(rule_type)),
                rule_parameter=str(rule_parameter),
                rule_policy=str(rule_policy),
                no_resolve=no_resolve,
            )
            custom_rules.append(single_rule)
            with open(plugin_config.rules_path, "w", encoding="utf-8") as file:
                yaml.dump([repr(rule) for rule in custom_rules], file)
            await UniMessage.text(f"添加规则成功: {repr(single_rule)}").finish()
        else:
            await UniMessage.text("参数错误").finish()
    if group_name:
        if len([g for g in custom_proxy_groups if g.name == group_name] + [g for g in config_proxy_groups if g.name == group_name]) > 0:
            await UniMessage.text("组名已存在").finish()
        suggest_value = ProxyGroupType.values()
        group_type = await suggest("请输入组类型", expect=suggest_value)
        proxies = []
        while True:
            rule_policy = await suggest(
                "请输入规则策略, accept 结束输入", expect=suggest_rule_policy + ["accept"], timeout=30
            )
            if rule_policy is None or str(rule_policy) == "accept":
                break
            proxies.append(str(rule_policy))
        if group_type is not None and proxies:
            group = ProxyGroup(
                name=str(group_name),
                type=ProxyGroupType.value_of(str(group_type)),
                proxies=proxies,
            )
            custom_proxy_groups.append(group)
            with open(plugin_config.proxy_groups_path, "w", encoding="utf-8") as file:
                custom_proxy_groups_str = [
                    {"name": group.name, "type": group.type.value, "proxies": group.proxies}
                    for group in custom_proxy_groups
                ]
                yaml.dump(custom_proxy_groups_str, file)
            await UniMessage.text(f"添加组成功: {group_name}").finish()
        else:
            await UniMessage.text("参数错误").finish()


@clash_setting.assign("remove")
async def remove_group_or_rule(args: Arparma = AlconnaMatches()):
    """移除自定义组或规则

    Args:
        args (Arparma, optional): _description_. Defaults to AlconnaMatches().
    """
    global config_proxy_groups, custom_proxy_groups, custom_rules
    rule_name = args.query[str]("rule")
    group_name = args.query[str]("group")
    if rule_name:
        await UniMessage.text("当前所有自定义规则").send()
        message = ""
        for i, rule in enumerate(custom_rules):
            message += f"{i}. {repr(rule)}\n"
        await UniMessage.text(message).send()
        index = await prompt("请输入要删除的规则序号")
        if (i := str(index)).isdigit():
            custom_rules.pop(int(i))
            with open(plugin_config.rules_path, "w", encoding="utf-8") as file:
                yaml.dump([repr(rule) for rule in custom_rules], file)
            await UniMessage.text("删除规则成功").finish()
        else:
            await UniMessage.text("参数错误").finish()
    if group_name:
        custom_proxy_groups = [group for group in custom_proxy_groups if group.name != group_name]
        with open(plugin_config.proxy_groups_path, "w", encoding="utf-8") as file:
            custom_proxy_groups_str = [
                {"name": group.name, "type": group.type.value, "proxies": group.proxies} for group in custom_proxy_groups
            ]
            yaml.dump(custom_proxy_groups_str, file)
        await UniMessage.text(f"删除组成功: {group_name}").finish()
    else:
        await UniMessage.text("参数错误").finish()


@clash_setting.assign("list.rule")
async def list_rule():
    await UniMessage.text("当前所有自定义规则").send()
    with open(plugin_config.rules_path, "r", encoding="utf-8") as file:
        yaml_str = file.read()
        md_str = f"```yaml\n{yaml_str}\n```"
        pic = await md_to_pic(md_str)
        await UniMessage.image(raw=pic).finish()


@clash_setting.assign("list.group")
async def list_group():
    await UniMessage.text("当前所有自定义组").send()
    with open(plugin_config.proxy_groups_path, "r", encoding="utf-8") as file:
        yaml_str = file.read()
        md_str = f"```yaml\n{yaml_str}\n```"
        pic = await md_to_pic(md_str)
        await UniMessage.image(raw=pic).finish()
