"""Logging setup for Cloding pipeline."""

import logging
import sys
from typing import Optional

LOG_CATEGORIES = {"SYSTEM", "STAGE", "DOCKER", "COST", "REVIEW", "FANOUT", "WORKSPACE"}

_initialized = False


class CategoryFormatter(logging.Formatter):
    """Formatter that includes category tag when present."""

    COLORS = {
        "DEBUG": "\033[36m",     # cyan
        "INFO": "\033[32m",      # green
        "WARNING": "\033[33m",   # yellow
        "ERROR": "\033[31m",     # red
        "CRITICAL": "\033[35m",  # magenta
    }
    RESET = "\033[0m"

    def __init__(self, use_color: bool = True) -> None:
        super().__init__()
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        category = getattr(record, "category", "")
        cat_tag = f"[{category}] " if category else ""

        level = record.levelname
        if self.use_color:
            color = self.COLORS.get(level, "")
            level_str = f"{color}{level:<8}{self.RESET}"
        else:
            level_str = f"{level:<8}"

        timestamp = self.formatTime(record, "%H:%M:%S")
        return f"{timestamp} {level_str} {cat_tag}{record.name}: {record.getMessage()}"


def init_logging(level: str = "INFO") -> None:
    """Initialize root logging for Cloding pipeline."""
    global _initialized
    if _initialized:
        return

    root = logging.getLogger("cloding")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # On Windows, stdout defaults to cp1252 which can't handle Unicode chars
    # (e.g., ✓ in review output). Use UTF-8 stream wrapper instead.
    stream = sys.stdout
    if sys.platform == "win32" and hasattr(stream, "buffer"):
        import io
        stream = io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace")

    handler = logging.StreamHandler(stream)
    use_color = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
    handler.setFormatter(CategoryFormatter(use_color=use_color))
    root.addHandler(handler)

    _initialized = True


def get_logger(name: str, category: Optional[str] = None) -> logging.Logger:
    """
    Get a logger for a component.

    Args:
        name: Logger name (e.g., "pipeline", "docker_runner")
        category: Optional category tag (e.g., "STAGE", "COST")

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(f"cloding.{name}")

    if category:
        # Use a filter to inject the category (not a global record factory,
        # which would affect all loggers)
        class CategoryFilter(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:
                if not hasattr(record, "category"):
                    record.category = category  # type: ignore[attr-defined]
                return True

        logger.addFilter(CategoryFilter())

    return logger
