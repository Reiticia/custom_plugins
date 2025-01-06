from dataclasses import dataclass
from enum import Enum
from google.generativeai.types.content_types import PartType

class Character(Enum):
    BOT = 1
    USER = 2

@dataclass
class ChatMsg:
    sender: Character
    content: list[PartType]