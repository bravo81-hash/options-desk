import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("DESK_DATA") or ROOT / "data")  # the cloud build uses its own folder
DATA.mkdir(exist_ok=True)


def load_config():
    cfg = json.loads((ROOT / "config.json").read_text())
    local = ROOT / "config.local.json"
    if local.exists():
        _merge(cfg, json.loads(local.read_text()))
    return cfg


def _merge(base, over):
    """Deep merge: config.local.json overrides key by key (personal settings live there, never uploaded)."""
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v


def expand(pattern):
    return os.path.expanduser(pattern)
