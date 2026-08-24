"""Certificate-first VCDIFF custom code-table optimizer."""

from .default_table import DEFAULT_TABLE
from .model import CodeEntry, Instruction, Pattern, WindowTrace

__all__ = [
    "CodeEntry",
    "DEFAULT_TABLE",
    "Instruction",
    "Pattern",
    "WindowTrace",
]

