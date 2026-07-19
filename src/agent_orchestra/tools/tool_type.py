from enum import Enum


class ToolType(str, Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    SEARCH = "search"
    DELEGATE = "delegate"
