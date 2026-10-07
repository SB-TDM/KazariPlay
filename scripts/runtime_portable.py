"""Keep trial bundle data separate from the installed application's data."""
import os
import sys
from pathlib import Path

if "--smoke-test" in sys.argv:
    if not os.environ.get("KAZARIPLAY_DATA_DIR", "").strip():
        raise RuntimeError("--smoke-test requires an explicit isolated KAZARIPLAY_DATA_DIR")
    from frozen_smoke import install
    install()

if not os.environ.get("KAZARIPLAY_DATA_DIR", "").strip():
    os.environ["KAZARIPLAY_DATA_DIR"] = str(Path(sys.executable).resolve().parent / "data")
