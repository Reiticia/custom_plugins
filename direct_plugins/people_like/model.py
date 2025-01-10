from dataclasses import dataclass
from enum import Enum
from google.genai.types import Part

class Character(Enum):
    BOT = 1
    USER = 2

@dataclass
class ChatMsg:
    sender: Character
    content: list[Part]