"""Service-layer error type and error codes."""


class GameError(Exception):
    """A game rule violation raised by the service layer."""

    def __init__(self, code: str, message: str) -> None:
        """Store the error code and Thai message; pass message to Exception."""
        super().__init__(message)
        self.code: str = code
        self.message: str = message


NOT_FOUND = "NOT_FOUND"
FORBIDDEN = "FORBIDDEN"
INSUFFICIENT_RESOURCES = "INSUFFICIENT_RESOURCES"
QUEUE_FULL = "QUEUE_FULL"
REQUIREMENTS_NOT_MET = "REQUIREMENTS_NOT_MET"
MAX_LEVEL = "MAX_LEVEL"
INVALID_SLOT = "INVALID_SLOT"
INVALID_TARGET = "INVALID_TARGET"
INVALID_UNITS = "INVALID_UNITS"
NO_UNITS = "NO_UNITS"
PROTECTED = "PROTECTED"
NOT_ENOUGH_CULTURE = "NOT_ENOUGH_CULTURE"
WORLD_ENDED = "WORLD_ENDED"
