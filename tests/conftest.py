import pytest
from git import Repo
from unittest.mock import MagicMock


@pytest.fixture
def mock_repo(monkeypatch):
    repo = MagicMock(spec=Repo)
    monkeypatch.setattr("ghchain.repo", repo)
    return repo
