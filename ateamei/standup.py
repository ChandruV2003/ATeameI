from __future__ import annotations

import os
import plistlib
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StandupSchedule:
    hour: int = 8
    minute: int = 30
    # launchd Weekday: 1=Sunday ... 7=Saturday
    weekdays: tuple[int, ...] = (2, 3, 4, 5, 6)  # Mon-Fri


def _config_dir() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "ateamei"


def standup_url_path() -> Path:
    return _config_dir() / "standup_url.txt"


def set_standup_url(url: str) -> None:
    url = url.strip()
    if not url:
        raise ValueError("Standup URL is required.")

    cfg_dir = _config_dir()
    cfg_dir.mkdir(parents=True, exist_ok=True)
    standup_url_path().write_text(url + "\n", encoding="utf-8")


def get_standup_url() -> str:
    p = standup_url_path()
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8").strip()


def join_standup() -> None:
    url = get_standup_url()
    if not url:
        raise FileNotFoundError(
            f"Standup URL not configured. Set it with: python -m ateamei standup set-url <url> (writes {standup_url_path()})"
        )
    subprocess.run(["open", url], check=False)


def _repo_root() -> Path:
    # /.../ATeamei/ateamei/standup.py -> repo root is parent of package dir
    return Path(__file__).resolve().parent.parent


def _standup_script_path() -> Path:
    return _repo_root() / "scripts" / "standup_join.sh"


def launchagent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / "com.chandruv.ateamei.standup.plist"


def write_launchagent(schedule: StandupSchedule | None = None) -> Path:
    schedule = schedule or StandupSchedule()

    script_path = _standup_script_path()
    if not script_path.exists():
        raise FileNotFoundError(f"Missing script at {script_path}")

    out_log = _config_dir() / "standup.out.log"
    err_log = _config_dir() / "standup.err.log"
    _config_dir().mkdir(parents=True, exist_ok=True)

    plist: dict = {
        "Label": "com.chandruv.ateamei.standup",
        "ProgramArguments": [str(script_path)],
        "StartCalendarInterval": [
            {"Weekday": wd, "Hour": schedule.hour, "Minute": schedule.minute} for wd in schedule.weekdays
        ],
        "LimitLoadToSessionType": "Aqua",
        "StandardOutPath": str(out_log),
        "StandardErrorPath": str(err_log),
    }

    dest = launchagent_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as f:
        plistlib.dump(plist, f)

    return dest
