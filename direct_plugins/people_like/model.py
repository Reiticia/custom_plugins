from dataclasses import dataclass
from enum import Enum
from typing import Optional
from google.genai.types import Part

class Character(Enum):
    BOT = 1
    USER = 2

@dataclass
class ChatMsg:
    sender: Character
    content: list[Part]


@dataclass
class GroupMemberDict:
    group_id: int
    members: dict[int, str]

    def add_member(self, user_id: int, user_name: str):
        self.members[user_id] = user_name

    def get_id_by_name(self, user_name: str) -> Optional[int]:
        for user_id, name in self.members.items():
            if name == user_name:
                return user_id
        return None