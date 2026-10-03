"""Compatibility entry for the organized variants tool directory."""
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).parent / 'variants' / 'verify-variant-artifacts.py'), run_name='__main__')
