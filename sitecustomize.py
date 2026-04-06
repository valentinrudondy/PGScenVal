from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent

for candidate in (ROOT / "PGscen-new", ROOT / "PGscen-main"):
    if candidate.is_dir():
        candidate_str = str(candidate)
        if candidate_str not in sys.path:
            sys.path.insert(0, candidate_str)
