import sys
from pathlib import Path

# Add backend/ to sys.path so test imports find session, snapshot, etc.
sys.path.insert(0, str(Path(__file__).parent.parent))
