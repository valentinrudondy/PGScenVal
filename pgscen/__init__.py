from pathlib import Path


_ROOT = Path(__file__).resolve().parent.parent
_PACKAGE_DIR = _ROOT / "PGscen-new" / "pgscen"

if not _PACKAGE_DIR.is_dir():
    _PACKAGE_DIR = _ROOT / "PGscen-main" / "pgscen"

if not _PACKAGE_DIR.is_dir():
    raise ModuleNotFoundError("Could not locate the bundled pgscen package.")

__path__ = [str(_PACKAGE_DIR)]
