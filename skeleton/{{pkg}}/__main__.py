"""Canonical ``python3 -m {{pkg}}`` entry point; works without package installation."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
