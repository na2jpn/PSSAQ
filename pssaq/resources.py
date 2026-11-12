"""Read bundled assets independently of the working directory."""
import sys
from pathlib import Path


def asset_path(name):
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
    return root / 'assets' / name


def license_path(name="LICENSE.md"):
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
    return root / name
