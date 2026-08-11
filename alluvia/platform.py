"""Per-OS data-root discovery. Existing dirs only; config overrides all."""
from __future__ import annotations
import glob
import os

_HOME = os.path.expanduser("~")
_WSL_USERS_GLOB = "/mnt/c/Users/*"


def _candidates(app: str) -> list[str]:
    home = _HOME
    out = [
        os.path.join(home, "Library", "Application Support", app),   # macOS
        os.path.join(home, ".config", app),                          # Linux
    ]
    appdata = os.environ.get("APPDATA")
    if appdata:                                                      # Windows-native
        out.append(os.path.join(appdata, app))
    out += [os.path.join(p, "AppData", "Roaming", app)               # WSL
            for p in glob.glob(_WSL_USERS_GLOB)]
    return out


def fork_roots(app: str) -> tuple[str, ...]:
    return tuple(sorted(p for p in _candidates(app) if os.path.isdir(p)))


def claude_code_root() -> str:
    return os.path.join(_HOME, ".claude", "projects")


_VSCODE_EDITORS = ("Code", "Code - Insiders", "Cursor", "VSCodium", "Windsurf")


def vscode_extension_dirs(publisher_ext: str) -> list[str]:
    """Existing `<editor>/User/globalStorage/<publisher_ext>/` dirs across editors + OSes."""
    out = []
    for editor in _VSCODE_EDITORS:
        for root in _candidates(editor):
            d = os.path.join(root, "User", "globalStorage", publisher_ext)
            if os.path.isdir(d):
                out.append(d)
    return sorted(set(out))
