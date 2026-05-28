"""Top-level package for ghchain."""

__author__ = """Hendrik Klug"""
__email__ = "hendrik.klug@gmail.com"


import sys
from pathlib import Path

from git import Repo
from loguru import logger

from ghchain.config import Config

try:
    repo = Repo(".", search_parent_directories=True)
except Exception:
    logger.error("Could not find a git repository in the current directory.")
    sys.exit(1)


def _find_config_path(repo: Repo) -> Path:
    worktree_config = Path(repo.working_tree_dir) / ".ghchain.toml"
    if worktree_config.exists():
        return worktree_config
    # GitPython returns common_dir as an unresolved path like
    # ".git/worktrees/<name>/../..", so resolve before taking .parent to land on
    # the main checkout. In a non-worktree repo this is the same directory as
    # working_tree_dir.
    return Path(repo.common_dir).resolve().parent / ".ghchain.toml"


config = Config.from_toml(_find_config_path(repo))
logger.remove()
logger.add(sys.stderr, level=config.log_level)
if config.log_file:
    logger.add(config.log_file, level=config.log_level)
