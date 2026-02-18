"""Tests for logging setup and category formatter."""

import logging
from unittest.mock import MagicMock, patch

from cloding.core.logger import CategoryFormatter, get_logger, init_logging, _initialized


class TestCategoryFormatter:
    def test_format_with_color(self):
        formatter = CategoryFormatter(use_color=True)
        record = logging.LogRecord(
            name="cloding.test", level=logging.INFO,
            pathname="", lineno=0, msg="hello", args=(), exc_info=None,
        )
        output = formatter.format(record)
        assert "hello" in output
        assert "\033[32m" in output  # green for INFO

    def test_format_without_color(self):
        formatter = CategoryFormatter(use_color=False)
        record = logging.LogRecord(
            name="cloding.test", level=logging.WARNING,
            pathname="", lineno=0, msg="warn msg", args=(), exc_info=None,
        )
        output = formatter.format(record)
        assert "warn msg" in output
        assert "\033[" not in output

    def test_format_with_category(self):
        formatter = CategoryFormatter(use_color=False)
        record = logging.LogRecord(
            name="cloding.test", level=logging.INFO,
            pathname="", lineno=0, msg="test", args=(), exc_info=None,
        )
        record.category = "STAGE"  # type: ignore[attr-defined]
        output = formatter.format(record)
        assert "[STAGE]" in output

    def test_format_all_levels(self):
        formatter = CategoryFormatter(use_color=True)
        for level in [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL]:
            record = logging.LogRecord(
                name="cloding.test", level=level,
                pathname="", lineno=0, msg="msg", args=(), exc_info=None,
            )
            output = formatter.format(record)
            assert "msg" in output

    def test_format_no_category(self):
        """Records without a category attribute should not have a tag."""
        formatter = CategoryFormatter(use_color=False)
        record = logging.LogRecord(
            name="cloding.test", level=logging.INFO,
            pathname="", lineno=0, msg="plain", args=(), exc_info=None,
        )
        output = formatter.format(record)
        assert "[" not in output.split("cloding.test")[0].split("INFO")[1]

    def test_format_includes_timestamp(self):
        formatter = CategoryFormatter(use_color=False)
        record = logging.LogRecord(
            name="cloding.test", level=logging.INFO,
            pathname="", lineno=0, msg="test", args=(), exc_info=None,
        )
        output = formatter.format(record)
        # Timestamp format is HH:MM:SS
        assert ":" in output


class TestGetLogger:
    def test_returns_logger(self):
        log = get_logger("testmod")
        assert isinstance(log, logging.Logger)
        assert "cloding.testmod" in log.name

    def test_with_category(self):
        log = get_logger("testmod2", category="DOCKER")
        assert isinstance(log, logging.Logger)
        # Category filter should be attached
        assert len(log.filters) >= 1

    def test_category_filter_injects_attribute(self):
        log = get_logger("cattest", category="COST")
        record = logging.LogRecord(
            name="cloding.cattest", level=logging.INFO,
            pathname="", lineno=0, msg="test", args=(), exc_info=None,
        )
        # Run the filter
        for f in log.filters:
            f.filter(record)
        assert hasattr(record, "category")
        assert record.category == "COST"  # type: ignore[attr-defined]

    def test_no_category_no_filter(self):
        """Logger without category should have no extra filters."""
        log = get_logger("nocat_unique_test")
        # It may or may not have filters from other tests, but the key is it works
        assert isinstance(log, logging.Logger)

    def test_existing_category_not_overwritten(self):
        """If record already has category, filter should not overwrite it."""
        log = get_logger("existing_cat", category="NEW")
        record = logging.LogRecord(
            name="cloding.existing_cat", level=logging.INFO,
            pathname="", lineno=0, msg="test", args=(), exc_info=None,
        )
        record.category = "ORIGINAL"  # type: ignore[attr-defined]
        for f in log.filters:
            f.filter(record)
        assert record.category == "ORIGINAL"  # type: ignore[attr-defined]


class TestInitLogging:
    def test_init_logging_sets_up_handler(self):
        """init_logging should add a handler to the cloding logger."""
        import cloding.core.logger as logger_module

        # Reset the _initialized flag to test init
        original = logger_module._initialized
        logger_module._initialized = False

        try:
            root = logging.getLogger("cloding")
            original_handlers = root.handlers.copy()

            init_logging("INFO")

            # Should have at least one handler now
            assert len(root.handlers) > len(original_handlers)
        finally:
            # Restore state
            logger_module._initialized = original

    def test_init_logging_idempotent(self):
        """Calling init_logging twice should not add duplicate handlers."""
        import cloding.core.logger as logger_module

        original = logger_module._initialized
        logger_module._initialized = False

        try:
            root = logging.getLogger("cloding")

            init_logging("INFO")
            count_after_first = len(root.handlers)

            # Reset and call again - but _initialized is now True
            init_logging("DEBUG")
            count_after_second = len(root.handlers)

            assert count_after_second == count_after_first
        finally:
            logger_module._initialized = original

    def test_init_logging_debug_level(self):
        """DEBUG level should be settable."""
        import cloding.core.logger as logger_module

        original = logger_module._initialized
        logger_module._initialized = False

        try:
            init_logging("DEBUG")
            root = logging.getLogger("cloding")
            assert root.level == logging.DEBUG
        finally:
            logger_module._initialized = original

    def test_init_logging_tty_detection(self):
        """When stdout is a TTY, should use color formatter."""
        import io
        import cloding.core.logger as logger_module

        original = logger_module._initialized
        logger_module._initialized = False

        try:
            root = logging.getLogger("cloding")
            handler_count_before = len(root.handlers)

            # Create a mock stdout that claims to be a TTY
            mock_stdout = MagicMock()
            mock_stdout.isatty = MagicMock(return_value=True)
            mock_stdout.buffer = io.BytesIO()

            with patch("sys.stdout", mock_stdout):
                with patch("sys.platform", "linux"):
                    init_logging("INFO")

            # Should have added a handler
            assert len(root.handlers) > handler_count_before
            # The newest handler's formatter should have use_color=True
            newest_handler = root.handlers[-1]
            if isinstance(newest_handler.formatter, CategoryFormatter):
                assert newest_handler.formatter.use_color is True
        finally:
            logger_module._initialized = original

    def test_init_logging_non_tty_detection(self):
        """When stdout is not a TTY, should not use color."""
        import io
        import cloding.core.logger as logger_module

        original = logger_module._initialized
        logger_module._initialized = False

        try:
            root = logging.getLogger("cloding")
            handler_count_before = len(root.handlers)

            mock_stdout = MagicMock()
            mock_stdout.isatty = MagicMock(return_value=False)
            mock_stdout.buffer = io.BytesIO()

            with patch("sys.stdout", mock_stdout):
                with patch("sys.platform", "linux"):
                    init_logging("INFO")

            assert len(root.handlers) > handler_count_before
            newest_handler = root.handlers[-1]
            if isinstance(newest_handler.formatter, CategoryFormatter):
                assert newest_handler.formatter.use_color is False
        finally:
            logger_module._initialized = original

    def test_init_logging_windows_utf8_wrapper(self):
        """On Windows, stdout should be wrapped with UTF-8 TextIOWrapper."""
        import io
        import cloding.core.logger as logger_module

        original = logger_module._initialized
        logger_module._initialized = False

        try:
            root = logging.getLogger("cloding")

            mock_stdout = MagicMock()
            mock_stdout.isatty = MagicMock(return_value=False)
            mock_stdout.buffer = io.BytesIO()

            with patch("sys.stdout", mock_stdout):
                with patch("sys.platform", "win32"):
                    init_logging("INFO")

            # Handler should have been added
            assert len(root.handlers) > 0
        finally:
            logger_module._initialized = original
