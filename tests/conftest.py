import sys
from unittest.mock import MagicMock

import pytest
from git import Repo


def is_debugging():
    """
    Check if pytest is run from a debugger.
    """
    return "debugpy" in sys.modules


# enable_stop_on_exceptions if the debugger is running during a test
# taken from https://stackoverflow.com/questions/62419998/how-can-i-get-pytest-to-not-catch-exceptions/62563106#62563106
if is_debugging():

    @pytest.hookimpl(tryfirst=True)
    def pytest_exception_interact(call):
        raise call.excinfo.value

    @pytest.hookimpl(tryfirst=True)
    def pytest_internalerror(excinfo):
        raise excinfo.value


@pytest.fixture(autouse=True)
def no_gpg_signing(monkeypatch):
    """Keep tests from invoking gpg when they create commits or tags."""
    monkeypatch.setenv("GIT_CONFIG_COUNT", "2")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "commit.gpgsign")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "false")
    monkeypatch.setenv("GIT_CONFIG_KEY_1", "tag.gpgsign")
    monkeypatch.setenv("GIT_CONFIG_VALUE_1", "false")


@pytest.fixture
def mock_repo(monkeypatch):
    repo = MagicMock(spec=Repo)
    monkeypatch.setattr("ghchain.repo", repo)
    return repo
