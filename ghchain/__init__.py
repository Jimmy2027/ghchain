"""Top-level package for ghchain."""

__author__ = """Hendrik Klug"""
__email__ = "hendrik.klug@gmail.com"
__version__ = "0.1.0"


import sys
from pathlib import Path

from git import Repo
from loguru import logger

from ghchain.config import Config

repo = Repo(".")

config = Config.from_toml(Path(repo.git_dir).parent / ".ghchain.toml")
logger.remove()
logger.add(sys.stderr, level=config.log_level)
if config.log_file:
    logger.add(config.log_file, level=config.log_level)
logger.info(f"Loaded config from {repo.git_dir}/.ghchain.toml")
logger.debug(f"Config: {config.to_dict()}")
