import os

import pytest


@pytest.fixture(autouse=True)
def change_test_dir(request, monkeypatch):
    monkeypatch.chdir(os.environ["TEST_REPO_DIR"])
