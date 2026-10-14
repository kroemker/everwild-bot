"""Committing the game state from inside the workflow (design §3, §17)."""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

logger = logging.getLogger("everwild.git")


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def commit_and_push(paths: list[Path], message: str, repo: Path = Path("."), retries: int = 4) -> bool:
    """Commits the given paths and pushes. Returns False if there was nothing to commit."""
    _git("add", "-A", "--", *[str(p) for p in paths], cwd=repo).check_returncode()
    if _git("diff", "--cached", "--quiet", cwd=repo).returncode == 0:
        return False
    _git("commit", "-m", message, cwd=repo).check_returncode()
    for attempt in range(retries):
        result = _git("push", cwd=repo)
        if result.returncode == 0:
            return True
        logger.warning("git push fehlgeschlagen (%s), versuche rebase", result.stderr.strip())
        _git("pull", "--rebase", cwd=repo)
        time.sleep(2 ** attempt)
    raise RuntimeError("git push ist mehrfach fehlgeschlagen")
