"""CLI entry point for Cloding pipeline."""

import argparse
import asyncio
import sys
from pathlib import Path

from cloding import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="cloding",
        description="Cloding — Claude Code with any model via OpenRouter. Multi-model pipeline.",
    )
    parser.add_argument("request", nargs="?", help="The coding request to execute")
    parser.add_argument(
        "-f", "--file",
        help="Read request from file instead of argument",
    )
    parser.add_argument(
        "-c", "--config",
        default="configs/default.yaml",
        help="Path to YAML pipeline config (default: configs/default.yaml)",
    )
    parser.add_argument(
        "-w", "--workspace",
        default=".",
        help="Path to target workspace directory (default: current dir)",
    )
    parser.add_argument(
        "--context-files",
        help="Comma-separated list of key files to examine",
    )
    parser.add_argument(
        "--no-docker",
        action="store_true",
        help="Run Claude Code locally instead of in Docker",
    )
    parser.add_argument(
        "--no-git",
        action="store_true",
        help="Skip git workspace preparation (branch creation, stash)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print pipeline config and exit without executing",
    )
    parser.add_argument(
        "--resume",
        metavar="STAGE",
        help="Resume from a specific stage (e.g., 'code')",
    )
    parser.add_argument(
        "--run-id",
        help="Run ID to resume from (used with --resume)",
    )
    parser.add_argument(
        "--prompts-dir",
        default="prompts",
        help="Directory containing prompt templates (default: prompts)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main() -> None:
    """Main CLI entry point."""
    # Load .env file from CWD or project root
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ModuleNotFoundError:
        pass  # dotenv is optional

    parser = build_parser()
    args = parser.parse_args()

    # Get request text
    request = args.request
    if args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"Error: Request file not found: {args.file}", file=sys.stderr)
            sys.exit(1)
        request = file_path.read_text(encoding="utf-8").strip()

    if not request and not args.dry_run:
        parser.error("A request is required (as argument or via -f/--file)")

    # Parse context files
    context_files = None
    if args.context_files:
        context_files = [f.strip() for f in args.context_files.split(",")]

    # Import here to avoid slow startup for --help/--version
    from cloding.orchestrator import run_pipeline

    result = asyncio.run(run_pipeline(
        request=request or "",
        config_path=args.config,
        workspace=args.workspace,
        context_files=context_files,
        no_docker=args.no_docker,
        no_git=args.no_git,
        dry_run=args.dry_run,
        resume_from=args.resume,
        run_id=args.run_id,
        verbose=args.verbose,
        prompts_dir=args.prompts_dir,
    ))

    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
