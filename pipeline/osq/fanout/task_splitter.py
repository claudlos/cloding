"""Parses PLAN.md into independent CodingTask objects for fan-out execution."""

import re

from osq.core.errors import StageError
from osq.core.logger import get_logger
from osq.pipeline.state import CodingTask

logger = get_logger("task_splitter", category="SYSTEM")


def split_tasks(plan_md: str) -> list[CodingTask]:
    """Parse PLAN.md Markdown content into CodingTask objects.

    Expects Markdown with ``### Task N: title`` sections where each task has:
    - **Files**: comma-separated file paths in backticks
    - **Priority**: integer (1 = highest)
    - **Description**: what to implement
    - **Context**: additional notes (optional)

    Args:
        plan_md: Raw Markdown content from PLAN.md

    Returns:
        List of CodingTask objects sorted by priority (1 = highest)
    """
    # Split on task headers: ### Task 1: Title
    task_pattern = re.compile(
        r"^###\s+Task\s+(\d+)\s*:\s*(.+)$", re.MULTILINE
    )
    matches = list(task_pattern.finditer(plan_md))

    if not matches:
        raise StageError(
            "PLAN.md contains no tasks. Expected '### Task N: title' headers."
        )

    tasks: list[CodingTask] = []
    for i, match in enumerate(matches):
        task_num = match.group(1)
        title = match.group(2).strip()

        # Extract the body between this header and the next (or end of string)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(plan_md)
        body = plan_md[start:end].strip()

        files = _extract_field(body, "Files")
        priority_str = _extract_field(body, "Priority")
        description = _extract_field(body, "Description")
        context = _extract_field(body, "Context")

        # Parse file list: backtick-wrapped, comma-separated
        files_list = _parse_file_list(files)

        # Parse priority (default to task number)
        try:
            priority = int(re.search(r"\d+", priority_str).group()) if priority_str else int(task_num)
        except (AttributeError, ValueError):
            priority = int(task_num)

        if not description and not title:
            logger.warning("Task %s has no description, skipping", task_num)
            continue

        task = CodingTask(
            task_id=f"task-{task_num}",
            description=description or title,
            files_to_modify=files_list,
            context=context,
            priority=priority,
        )
        tasks.append(task)

    tasks.sort(key=lambda t: t.priority)
    logger.info("Parsed %d coding tasks from PLAN.md", len(tasks))

    _check_file_overlaps(tasks)
    return tasks


def _extract_field(body: str, field_name: str) -> str:
    """Extract a bold-prefixed field value from a task body.

    Matches patterns like:
    - **Files**: `path/to/file.py`, `other.py`
    - **Description**: What to implement.
    """
    pattern = re.compile(
        rf"[-*]\s*\*\*{field_name}\*\*\s*:\s*(.+?)(?=\n[-*]\s*\*\*|\n###|\n##|\Z)",
        re.DOTALL,
    )
    match = pattern.search(body)
    if match:
        return match.group(1).strip()
    return ""


def _parse_file_list(files_str: str) -> list[str]:
    """Parse backtick-wrapped file paths from a field value.

    Input:  "`path/to/file.py`, `other.py`"
    Output: ["path/to/file.py", "other.py"]
    """
    if not files_str:
        return []
    # Find all backtick-wrapped paths
    paths = re.findall(r"`([^`]+)`", files_str)
    if paths:
        return paths
    # Fallback: split on commas and strip
    return [f.strip() for f in files_str.split(",") if f.strip()]


def _check_file_overlaps(tasks: list[CodingTask]) -> None:
    """Warn if multiple tasks modify the same files."""
    file_owners: dict[str, list[str]] = {}
    for task in tasks:
        for f in task.files_to_modify:
            file_owners.setdefault(f, []).append(task.task_id)

    for filepath, owners in file_owners.items():
        if len(owners) > 1:
            logger.warning(
                "File '%s' is targeted by multiple tasks: %s. "
                "This may cause conflicts in parallel execution.",
                filepath,
                ", ".join(owners),
            )
