#!/usr/bin/env python3
"""Entry point for GUI executable (PyInstaller compatible)."""

import sys
from pathlib import Path

# Add src to path for PyInstaller
src_path = Path(__file__).parent / "src"
if src_path.exists():
    sys.path.insert(0, str(src_path))

from tplink_nvr_export.gui import main

if __name__ == "__main__":
    main()
