"""Top-level package for ghchain."""

__author__ = """Hendrik Klug"""
__email__ = "hendrik.klug@gmail.com"
__version__ = "0.2.0"


import sys
from pathlib import Path

from git import Repo
from loguru import logger

from ghchain.config import Config

try:
    repo = Repo(".")
except Exception:
    logger.error("Could not find a git repository in the current directory.")
    sys.exit(1)

config = Config.from_toml(Path(repo.git_dir).parent / ".ghchain.toml")
logger.remove()
logger.add(sys.stderr, level=config.log_level)
if config.log_file:
    logger.add(config.log_file, level=config.log_level)


if (
    toml_fn := Path(repo.git_dir)
    .parent.parent.parent.joinpath(".ghchain.toml")
    .exists()
):
    logger.info(f"Loaded config from {toml_fn}")
logger.debug(f"Config: {config.to_dict()}")
