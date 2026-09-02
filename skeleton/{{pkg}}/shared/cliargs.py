"""Argument parser implementing the shared contract that usage errors exit 1.

Standard argparse exits 2 for invalid arguments, while the generated CLI reserves only
0/75/111/1. This subclass changes the exit code and preserves the standard usage and error
messages. Subparsers inherit the class automatically through ``parser_class=type(parent)``.

Vendored from tool-template and owned by the generated repository.
"""
from __future__ import annotations

import argparse
import sys


class ArgumentParser(argparse.ArgumentParser):
    """Behave like ``argparse.ArgumentParser`` but exit 1 for usage errors."""

    def error(self, message: str):
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")
