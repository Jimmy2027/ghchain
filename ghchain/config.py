from dataclasses import dataclass
from pathlib import Path

import tomllib


@dataclass(frozen=True)
class Config:
    workflows: list[str]

    @classmethod
    def from_toml(cls, toml_fn: Path):
        if not toml_fn.exists():
            return cls(workflows=[])
        toml_string = toml_fn.read_text()
        toml_dict = tomllib.loads(toml_string)
        return cls(**toml_dict)
