#!/usr/bin/env python3
"""Deprecated shim: the driver now lives in the `minixprint` package."""
import sys

print("minix.py is deprecated; use `minixprint` (pip install -e .) -- see docs/CLI.md", file=sys.stderr)
from minixprint.cli import main  # noqa: E402

sys.exit(main())
