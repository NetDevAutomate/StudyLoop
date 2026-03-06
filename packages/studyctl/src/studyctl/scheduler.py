"""Cross-platform scheduled job management (macOS launchd + Linux systemd/cron)."""

from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

JOBS_DIR = Path.home() / ".config" / "studyctl" / "jobs"


@dataclass
class Job:
    name: str
    command: str  # Uses ~ for portability
    schedule: str  # Human-readable: "every 2h", "daily 7am"
    description: str = ""


DEFAULT_JOBS = [
    Job(
        "session-export", "~/.local/bin/session-export", "every 2h", "Extract agent sessions to DB"
    ),
    Job(
        "studyctl-sync", "~/.local/bin/studyctl sync --all", "daily 7am", "Sync notes to NotebookLM"
    ),
    Job("studyctl-push", "~/.local/bin/studyctl state push", "every 4h", "Push state to hub"),
]


def _is_macos() -> bool:
    return platform.system() == "Darwin"


# ── macOS launchd ──────────────────────────────────────────────────────────


def _launchd_plist(job: Job, username: str) -> str:
    home = f"/Users/{username}" if _is_macos() else f"/home/{username}"
    cmd_parts = job.command.replace("~", home).split()
    args_xml = "\n        ".join(f"<string>{a}</string>" for a in cmd_parts)

    hour_tpl = "<key>Hour</key><integer>{h}</integer>"
    min_tpl = "<key>Minute</key><integer>{m}</integer>"

    def _cal_dict(h: int, m: int = 0) -> str:
        return f"        <dict>{hour_tpl.format(h=h)}{min_tpl.format(m=m)}</dict>"

    cal_key = "    <key>StartCalendarInterval</key>\n"
    if "every 2h" in job.schedule:
        entries = "\n".join(_cal_dict(h) for h in range(8, 23, 2))
        schedule = f"{cal_key}    <array>\n{entries}\n    </array>"
    elif "every 4h" in job.schedule:
        entries = "\n".join(_cal_dict(h, 30) for h in range(8, 23, 4))
        schedule = f"{cal_key}    <array>\n{entries}\n    </array>"
    elif "daily" in job.schedule:
        hour = 7
        if "am" in job.schedule:
            hour = int(job.schedule.split("daily")[1].strip().replace("am", "").strip())
        schedule = (
            f"{cal_key}"
            "    <dict>\n"
            f"        {hour_tpl.format(h=hour)}\n"
            f"        {min_tpl.format(m=0)}\n"
            "    </dict>"
        )
    else:
        schedule = "    <key>StartInterval</key>\n    <integer>3600</integer>"

    return dedent(f"""\
    <?xml version="1.0" encoding="UTF-8"?>
    <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
    <plist version="1.0">
    <dict>
        <key>Label</key>
        <string>com.studyctl.{job.name}</string>
        <key>ProgramArguments</key>
        <array>
            {args_xml}
        </array>
    {schedule}
        <key>StandardOutPath</key>
        <string>{home}/.local/share/studyctl/logs/{job.name}.log</string>
        <key>StandardErrorPath</key>
        <string>{home}/.local/share/studyctl/logs/{job.name}.err</string>
        <key>EnvironmentVariables</key>
        <dict>
            <key>PATH</key>
            <string>{home}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
        </dict>
    </dict>
    </plist>""")


def _launchd_install(job: Job, username: str) -> bool:
    label = f"com.studyctl.{job.name}"
    plist_dir = Path.home() / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_path = plist_dir / f"{label}.plist"

    plist_path.write_text(_launchd_plist(job, username))
    subprocess.run(["launchctl", "bootout", f"gui/{_uid()}/{label}"], capture_output=True)
    result = subprocess.run(
        ["launchctl", "bootstrap", f"gui/{_uid()}", str(plist_path)], capture_output=True
    )
    return result.returncode == 0


def _launchd_remove(job: Job) -> bool:
    label = f"com.studyctl.{job.name}"
    subprocess.run(["launchctl", "bootout", f"gui/{_uid()}/{label}"], capture_output=True)
    plist = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    if plist.exists():
        plist.unlink()
    return True


def _launchd_list() -> list[dict]:
    result = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    jobs = []
    for line in result.stdout.splitlines():
        if "com.studyctl." in line:
            parts = line.split()
            jobs.append(
                {
                    "name": parts[2].replace("com.studyctl.", ""),
                    "status": parts[0],
                    "label": parts[2],
                }
            )
    return jobs


def _uid() -> int:
    import os

    return os.getuid()


# ── Linux cron ─────────────────────────────────────────────────────────────


def _cron_expression(job: Job) -> str:
    if "every 2h" in job.schedule:
        return "0 8-22/2 * * *"
    elif "every 4h" in job.schedule:
        return "30 8-22/4 * * *"
    elif "daily" in job.schedule:
        hour = 7
        if "am" in job.schedule:
            hour = int(job.schedule.split("daily")[1].strip().replace("am", "").strip())
        return f"0 {hour} * * *"
    return "0 * * * *"


def _cron_line(job: Job) -> str:
    home = str(Path.home())
    cmd = job.command.replace("~", home)
    log = f"{home}/.local/share/studyctl/logs/{job.name}.log"
    path_dirs = [
        f"{home}/.local/bin",
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
    ]
    path = "PATH=" + ":".join(path_dirs)
    cron = _cron_expression(job)
    return f"{cron} {path} {cmd} >> {log} 2>&1 # studyctl:{job.name}"


def _cron_install(job: Job) -> bool:
    marker = f"# studyctl:{job.name}"
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    existing = result.stdout if result.returncode == 0 else ""
    # Remove old entry
    lines = [line for line in existing.splitlines() if marker not in line]
    lines.append(_cron_line(job))
    subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True, check=True)
    return True


def _cron_remove(job: Job) -> bool:
    marker = f"# studyctl:{job.name}"
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if result.returncode != 0:
        return True
    lines = [line for line in result.stdout.splitlines() if marker not in line]
    subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True, check=True)
    return True


def _cron_list() -> list[dict]:
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if result.returncode != 0:
        return []
    jobs = []
    for line in result.stdout.splitlines():
        if "# studyctl:" in line:
            name = line.split("# studyctl:")[1].strip()
            jobs.append({"name": name, "cron": line.split("#")[0].strip()})
    return jobs


# ── Public API ─────────────────────────────────────────────────────────────


def install_job(job: Job, username: str | None = None) -> bool:
    Path.home().joinpath(".local/share/studyctl/logs").mkdir(parents=True, exist_ok=True)
    username = username or Path.home().name
    if _is_macos():
        return _launchd_install(job, username)
    return _cron_install(job)


def remove_job(job: Job) -> bool:
    if _is_macos():
        return _launchd_remove(job)
    return _cron_remove(job)


def list_jobs() -> list[dict]:
    if _is_macos():
        return _launchd_list()
    return _cron_list()


def install_all(username: str | None = None) -> list[str]:
    installed = []
    for job in DEFAULT_JOBS:
        if install_job(job, username):
            installed.append(job.name)
    return installed


def remove_all() -> list[str]:
    removed = []
    for job in DEFAULT_JOBS:
        if remove_job(job):
            removed.append(job.name)
    return removed
