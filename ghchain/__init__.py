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
    # In a worktree, common_dir points to the main repo's .git, so its parent
    # is the main checkout's working tree. In a non-worktree checkout this
    # resolves to the same path as working_tree_dir.
    return Path(repo.common_dir).parent / ".ghchain.toml"


config = Config.from_toml(_find_config_path(repo))
logger.remove()
logger.add(sys.stderr, level=config.log_level)
if config.log_file:
    logger.add(config.log_file, level=config.log_level)
