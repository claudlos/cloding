"""Custom exception hierarchy for Cloding pipeline."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ErrorCategory(Enum):
    CONFIG = "config"
    STAGE = "stage"
    DOCKER = "docker"
    COST = "cost"
    REVIEW = "review"
    WORKSPACE = "workspace"


@dataclass(frozen=True)
class ErrorContext:
    category: ErrorCategory
    stage: str
    message: str
    suggested_action: str


class OSQError(Exception):
    """Base exception for Cloding pipeline."""

    def __init__(self, message: str, context: Optional[ErrorContext] = None) -> None:
        super().__init__(message)
        self.context = context


class ConfigError(OSQError):
    """Raised when YAML config is invalid or missing required values."""


class StageError(OSQError):
    """Raised when a pipeline stage fails."""


class DockerError(OSQError):
    """Raised when Docker operations fail."""


class CostLimitError(OSQError):
    """Raised when cost budget is exceeded."""


class ReviewRejectedError(OSQError):
    """Raised when review loop exhausts max iterations without passing."""


class WorkspaceError(OSQError):
    """Raised when workspace preparation fails (not a git repo, dirty state, etc.)."""
