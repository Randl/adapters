import sys
from pathlib import Path

# The adapter is a separate package, not a dependency of the Harbor CLI.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
