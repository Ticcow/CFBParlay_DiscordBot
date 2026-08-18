import logging
import subprocess
from pathlib import Path

from bot.parlays import repository

logger = logging.getLogger("degen_bot.patch_notes")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
STATE_KEY = "last_announced_commit"
MAX_COMMITS_SHOWN = 15


def _run_git(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=10, check=True
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None


def _current_commit() -> str | None:
    return _run_git("rev-parse", "HEAD")


def _commit_subjects_since(old_commit: str, new_commit: str) -> list[str] | None:
    output = _run_git("log", "--pretty=format:%s", f"{old_commit}..{new_commit}")
    if output is None:
        return None
    return [line for line in output.splitlines() if line]


async def announce_if_updated(bot) -> None:
    """Compares the commit this process is actually running against whatever was
    last announced and, if different, posts what changed since then. A crash
    that gets auto-restarted by the watchdog leaves the commit hash unchanged,
    so this only ever fires on a real deploy - not every time the process
    happens to come back up."""
    current = _current_commit()
    if current is None:
        return  # not a git checkout, or git isn't on PATH - nothing to compare

    previous = repository.get_state(bot.conn, STATE_KEY)
    if previous == current:
        return

    if previous is None:
        repository.set_state(bot.conn, STATE_KEY, current)
        return  # first run ever - nothing to diff against yet, just start tracking

    subjects = _commit_subjects_since(previous, current)
    if not subjects:
        repository.set_state(bot.conn, STATE_KEY, current)
        return

    shown = subjects[:MAX_COMMITS_SHOWN]
    lines = [f"- {subject}" for subject in shown]
    if len(subjects) > MAX_COMMITS_SHOWN:
        lines.append(f"- ...and {len(subjects) - MAX_COMMITS_SHOWN} more")

    message = "🔧 **Degen Bot updated:**\n" + "\n".join(lines)
    await bot.announce(message)
    repository.set_state(bot.conn, STATE_KEY, current)
