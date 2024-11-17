from enum import Enum

from dataclasses import dataclass


class RuleType(Enum):
    """规则类型
    """

    DOMAIN = "DOMAIN"
    DOMAIN_SUFFIX = "DOMAIN-SUFFIX"
    DOMAIN_KEYWORD = "DOMAIN-KEYWORD"
    GEOIP = "GEOIP"
    IP_CIDR = "IP-CIDR"
    IP_CIDR6 = "IP-CIDR6"
    SRC_IP_CIDR = "SRC-IP-CIDR"
    SRC_PORT = "SRC-PORT"
    DST_PORT = "DST-PORT"
    PROCESS_NAME = "PROCESS-NAME"
    PROCESS_PATH = "PROCESS-PATH"
    IPSET = "IPSET"
    RULE_SET = "RULE-SET"
    SCRIPT = "SCRIPT"
    MATCH = "MATCH"

    @classmethod
    def value_of(cls, value) -> "RuleType":
        for _, t in cls.__members__.items():
            if t.value == value:
                return t
        else:
            raise ValueError(f"'{cls.__name__}' enum not found for '{value}'")

    @classmethod
    def values(cls) -> list[str]:
        return [t.value for _, t in cls.__members__.items()]


@dataclass(repr=False)
class SingleRule:
    """单条规则"""

    rule_type: RuleType
    rule_parameter: str
    rule_policy: str
    no_resolve: bool = False

    def __repr__(self) -> str:
        res = self.rule_type.value + "," + self.rule_parameter + "," + self.rule_policy
        return res + ",no-resolve" if self.no_resolve else res


class ProxyGroupType(Enum):
    """代理组类型
    """

    RELAY = "relay"
    URL_TEST = "url-test"
    FALLBACK = "fallback"
    LOAD_BALANCE = "load-balance"
    SELECT = "select"

    @classmethod
    def value_of(cls, value) -> "ProxyGroupType":
        for _, t in cls.__members__.items():
            if t.value == value:
                return t
        else:
            raise ValueError(f"'{cls.__name__}' enum not found for '{value}'")

    @classmethod
    def values(cls) -> list[str]:
        return [t.value for _, t in cls.__members__.items()]


@dataclass
class ProxyGroup:
    name: str
    type: ProxyGroupType
    proxies: list[str]

