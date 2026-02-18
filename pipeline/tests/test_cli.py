"""Tests for CLI argument parsing and main entry point."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from osq.cli.main import build_parser, main


class TestDunderMain:
    def test_dunder_main_calls_main(self):
        """python -m osq should call main()."""
        with patch("osq.cli.main.main", side_effect=SystemExit(0)) as mock_main:
            with pytest.raises(SystemExit):
                import importlib
                import osq.__main__
                importlib.reload(osq.__main__)
            mock_main.assert_called()


class TestBuildParser:
    def test_parser_created(self):
        parser = build_parser()
        assert parser is not None
        assert parser.prog == "cloding"

    def test_default_config(self):
        parser = build_parser()
        args = parser.parse_args(["test request"])
        assert args.config == "configs/default.yaml"

    def test_default_workspace(self):
        parser = build_parser()
        args = parser.parse_args(["test request"])
        assert args.workspace == "."

    def test_all_flags(self):
        parser = build_parser()
        args = parser.parse_args([
            "-c", "myconfig.yaml",
            "-w", "/home/user/project",
            "--context-files", "a.py,b.py",
            "--no-docker",
            "--no-git",
            "--dry-run",
            "--resume", "code",
            "--run-id", "abc-123",
            "--prompts-dir", "/prompts",
            "-v",
            "the request",
        ])
        assert args.config == "myconfig.yaml"
        assert args.workspace == "/home/user/project"
        assert args.context_files == "a.py,b.py"
        assert args.no_docker is True
        assert args.no_git is True
        assert args.dry_run is True
        assert args.resume == "code"
        assert args.run_id == "abc-123"
        assert args.prompts_dir == "/prompts"
        assert args.verbose is True
        assert args.request == "the request"

    def test_file_flag(self):
        parser = build_parser()
        args = parser.parse_args(["-f", "request.txt"])
        assert args.file == "request.txt"
        assert args.request is None

    def test_no_request_with_dry_run(self):
        parser = build_parser()
        args = parser.parse_args(["--dry-run"])
        assert args.request is None
        assert args.dry_run is True


class TestMain:
    def test_file_not_found_exits(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "argv", [
            "cloding", "-f", str(tmp_path / "nonexistent.txt"),
        ])
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    def test_no_request_no_dry_run_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["cloding"])
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code != 0

    def test_reads_request_from_file(self, tmp_path, monkeypatch):
        req_file = tmp_path / "req.txt"
        req_file.write_text("  My request  \n", encoding="utf-8")

        mock_result = MagicMock()
        mock_result.success = True

        monkeypatch.setattr(sys, "argv", [
            "cloding", "-f", str(req_file), "--dry-run",
            "-c", str(tmp_path / "config.yaml"),
        ])

        # Create a config file too
        (tmp_path / "config.yaml").write_text("""
name: test
models:
  qwen:
    provider: openrouter
    model_id: qwen/qwen3-coder-next
    api_key_env: OPENROUTER_API_KEY
    cost_per_mtok_input: 0.07
    cost_per_mtok_output: 0.30
stages:
  - name: code
    model: qwen
    prompt_file: prompts/code.txt
""", encoding="utf-8")

        # Dry run doesn't need run_pipeline to fully execute
        with pytest.raises(SystemExit) as exc_info:
            main()
        # Dry run returns success, so exit code 0
        assert exc_info.value.code == 0

    def test_main_calls_run_pipeline_and_exits(self, tmp_path, monkeypatch):
        """main() should call asyncio.run(run_pipeline(...)) and exit with correct code."""
        mock_result = MagicMock()
        mock_result.success = True

        monkeypatch.setattr(sys, "argv", [
            "cloding", "test request",
            "-c", str(tmp_path / "config.yaml"),
            "--no-docker", "--no-git",
        ])

        (tmp_path / "config.yaml").write_text("""
name: test
models:
  qwen:
    provider: openrouter
    model_id: qwen/qwen3-coder-next
    api_key_env: OPENROUTER_API_KEY
    cost_per_mtok_input: 0.07
    cost_per_mtok_output: 0.30
stages:
  - name: code
    model: qwen
    prompt_file: prompts/code.txt
""", encoding="utf-8")

        with patch("osq.cli.main.asyncio.run", return_value=mock_result):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

    def test_main_failure_exits_with_1(self, tmp_path, monkeypatch):
        """When pipeline fails, main() should exit with code 1."""
        mock_result = MagicMock()
        mock_result.success = False

        monkeypatch.setattr(sys, "argv", [
            "cloding", "test request",
            "-c", str(tmp_path / "config.yaml"),
            "--no-docker", "--no-git",
        ])

        (tmp_path / "config.yaml").write_text("""
name: test
models:
  qwen:
    provider: openrouter
    model_id: qwen/qwen3-coder-next
    api_key_env: OPENROUTER_API_KEY
    cost_per_mtok_input: 0.07
    cost_per_mtok_output: 0.30
stages:
  - name: code
    model: qwen
    prompt_file: prompts/code.txt
""", encoding="utf-8")

        with patch("osq.cli.main.asyncio.run", return_value=mock_result):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    def test_dotenv_import_failure_is_silent(self, tmp_path, monkeypatch):
        """When python-dotenv is not installed, main() should still work."""
        import builtins

        mock_result = MagicMock()
        mock_result.success = True

        monkeypatch.setattr(sys, "argv", [
            "cloding", "test request",
            "-c", str(tmp_path / "config.yaml"),
            "--no-docker", "--no-git",
        ])

        (tmp_path / "config.yaml").write_text("""
name: test
models:
  qwen:
    provider: openrouter
    model_id: qwen/qwen3-coder-next
    api_key_env: OPENROUTER_API_KEY
    cost_per_mtok_input: 0.07
    cost_per_mtok_output: 0.30
stages:
  - name: code
    model: qwen
    prompt_file: prompts/code.txt
""", encoding="utf-8")

        original_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "dotenv":
                raise ModuleNotFoundError("No module named 'dotenv'")
            return original_import(name, *args, **kwargs)

        with patch("osq.cli.main.asyncio.run", return_value=mock_result):
            with patch("builtins.__import__", side_effect=_mock_import):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 0

    def test_context_files_parsing(self, tmp_path, monkeypatch):
        """Context files should be split by comma."""
        mock_result = MagicMock()
        mock_result.success = True

        (tmp_path / "config.yaml").write_text("""
name: test
models:
  qwen:
    provider: openrouter
    model_id: qwen/qwen3-coder-next
    api_key_env: OPENROUTER_API_KEY
    cost_per_mtok_input: 0.07
    cost_per_mtok_output: 0.30
stages:
  - name: code
    model: qwen
    prompt_file: prompts/code.txt
""", encoding="utf-8")

        monkeypatch.setattr(sys, "argv", [
            "cloding", "--dry-run",
            "-c", str(tmp_path / "config.yaml"),
            "--context-files", "a.py, b.py, c.py",
            "test",
        ])

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
