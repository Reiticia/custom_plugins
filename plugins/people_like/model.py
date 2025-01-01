from dataclasses import dataclass
from enum import Enum

class Character(Enum):
    BOT = 1
    USER = 2

@dataclass
class ChatMsg:
    sender: Character
    content: str