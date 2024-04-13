from dataclasses import dataclass
from pathlib import Path

import tomllib

from ghchain.git_utils import get_git_base_dir


@dataclass(frozen=True)
class Config:
    workflows: list[str]
    branch_name_template: str = "{git_config_author}-{pr_id}"

    @classmethod
    def from_toml(cls, toml_fn: Path):
        if not toml_fn.exists():
            return cls(workflows=[])
        toml_string = toml_fn.read_text()
        toml_dict = tomllib.loads(toml_string)
        return cls(**toml_dict)


config = Config.from_toml(get_git_base_dir() / ".ghchain.toml")
