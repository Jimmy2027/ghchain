import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import tomllib
from loguru import logger

logger.remove()


def get_git_base_dir() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True
    )
    return Path(result.stdout.strip())


CONFIG_FN = get_git_base_dir() / ".ghchain.toml"


@dataclass(frozen=True)
class Config:
    workflows: list[str]
    git_username: str
    base_branch: str = "origin/main"
    branch_name_template: str = "{git_config_author}-{pr_id}"
    delete_branch_after_merge: bool = True

    # logging
    log_file: Path = get_git_base_dir() / "ghchain.log"
    log_level: str = "INFO"

    @classmethod
    def from_toml(cls, toml_fn: Path):
        git_username = subprocess.getoutput("git config user.name")
        if not toml_fn.exists():
            return cls(workflows=[], git_username=git_username)
        toml_string = toml_fn.read_text()
        toml_dict = tomllib.loads(toml_string)
        return cls(**toml_dict, git_username=git_username)


config = Config.from_toml(CONFIG_FN)
logger.add(sys.stderr, level=config.log_level)
logger.add(config.log_file, level=config.log_level)
logger.info(f"Loaded config from {CONFIG_FN}")
logger.info(f"Config: {config}")
