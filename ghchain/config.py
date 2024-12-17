import subprocess
from pathlib import Path
from typing import List

import tomllib
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Config(BaseModel):
    model_config = ConfigDict(frozen=True)

    workflows: List[str] = Field(default_factory=list)
    git_username: str = Field(default="")
    base_branch: str = Field(default="origin/main")
    branch_name_template: str = Field(default="{git_config_author}-{pr_id}")
    delete_branch_after_merge: bool = Field(default=True)

    # regex pattern to detect linked issues in commit messages
    issue_pattern: str = Field(default=r"\(#(\d+)\)")

    # logging
    log_file: Path | None = Field(default=None)
    log_level: str = Field(default="INFO")

    @field_validator("git_username")
    @classmethod
    def set_git_username(cls, v):
        return v or subprocess.getoutput("git config user.name")

    @classmethod
    def from_toml(cls, toml_fn: Path):
        if not toml_fn.exists():
            logger.warning(f"No config file found at {toml_fn}. Using default values.")
            return cls()
        toml_string = toml_fn.read_text()
        toml_dict = tomllib.loads(toml_string)
        return cls(**toml_dict)

    def to_dict(self):
        return self.model_dump()
