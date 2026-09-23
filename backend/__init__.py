"""Always use the pinned upstream code shipped with this workbench."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'vendor'/'wewrite'/'src'))
