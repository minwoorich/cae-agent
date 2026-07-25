"""Command-line interface for CAE Agent."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from cae_agent import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level command-line parser."""
    parser = argparse.ArgumentParser(
        prog="cae-agent",
        description=(
            "AI-assisted automation for Ansys SpaceClaim and Mechanical."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CAE Agent command-line interface."""
    parser = build_parser()
    parser.parse_args(argv)
    return 0
