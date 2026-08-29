"""In-app auto-update.

The installed app checks the project's GitHub Releases on startup; if a
newer version is published it downloads that release's installer and, on
the user's nod (or when they next close the app), runs it silently. The
installer shares its AppId with the running install, so it upgrades in
place — no uninstall, no admin prompt (the install is per-user).

Only active in a frozen (PyInstaller) build — running from source does
nothing, so `python main.py` never phones home.
"""
import os
import subprocess
import sys
import tempfile

# `requests` is imported lazily (see _requests()) — it's only touched on a
# background thread after launch, and keeping it off the startup path
# shaves ~1s off app start.
from clearscanner._version import __version__

REPO = "manasij123/desktop-scanner"
_LATEST_RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"
_HTTP_TIMEOUT = 15

# DETACHED_PROCESS: the relauncher .cmd gets no console and outlives this
# process, which is about to exit. (Don't OR in CREATE_NO_WINDOW — Windows
# rejects the two together.)
_DETACHED = 0x00000008  # DETACHED_PROCESS


def _requests():
    import requests
    return requests


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def _version_tuple(text: str) -> tuple[int, int, int]:
    """'v1.2.3', '1.2.3-beta' -> (1, 2, 3). Non-numeric parts read as 0."""
    parts = []
    for chunk in text.strip().lstrip("vV").split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def check_for_update():
    """Return (version, installer_url, release_notes) for a newer release, or
    None. Every failure path (offline, rate-limited, no .exe asset, not a
    frozen build) returns None — an update check must never be disruptive.
    """
    if not is_frozen():
        return None
    try:
        resp = _requests().get(
            _LATEST_RELEASE_API,
            timeout=_HTTP_TIMEOUT,
            headers={"Accept": "application/vnd.github+json"},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None

    tag = str(data.get("tag_name", ""))
    if not tag or _version_tuple(tag) <= _version_tuple(__version__):
        return None

    installer_url = None
    for asset in data.get("assets", []):
        name = str(asset.get("name", "")).lower()
        if name.endswith(".exe") and "setup" in name:
            installer_url = asset.get("browser_download_url")
            break
    if not installer_url:
        return None

    return tag.lstrip("vV"), installer_url, str(data.get("body") or "").strip()


def download_installer(url: str, progress=None) -> str:
    """Stream the installer to a temp .exe and return its path. `progress`,
    if given, is called with a 0.0-1.0 fraction as bytes arrive."""
    fd, path = tempfile.mkstemp(prefix="DesktopScanner-Update-", suffix=".exe")
    os.close(fd)
    try:
        with _requests().get(url, stream=True, timeout=_HTTP_TIMEOUT) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length", 0))
            written = 0
            with open(path, "wb") as out:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    out.write(chunk)
                    written += len(chunk)
                    if progress and total:
                        progress(min(1.0, written / total))
    except Exception:
        _silent_unlink(path)
        raise
    return path


def apply_update(installer_path: str, relaunch: bool = True) -> None:
    """Start the silent in-place upgrade and hand control to it. The caller
    must quit the app right after — the installer replaces files this
    process has open.

    A tiny detached .cmd runs the installer, waits for it, then (optionally)
    relaunches the app. Doing the relaunch here rather than via the
    installer's [Run] section keeps it working in /VERYSILENT mode.
    """
    flags = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NOCANCEL"
    exe = sys.executable if (relaunch and is_frozen()) else None

    script = installer_path + ".apply.cmd"
    lines = ["@echo off", f'"{installer_path}" {flags}']
    if exe:
        lines.append(f'start "" "{exe}"')
    lines.append(f'del "{installer_path}" 2>nul')
    lines.append('del "%~f0" 2>nul')
    with open(script, "w", encoding="ascii") as f:
        f.write("\r\n".join(lines) + "\r\n")

    subprocess.Popen(["cmd", "/c", script], creationflags=_DETACHED, close_fds=True)


def _silent_unlink(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
