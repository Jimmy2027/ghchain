#!/usr/bin/env python

"""Tests for `ghchain` package."""

import json
import os
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from ghchain import cli

my_test_repo = Path("~/ssrc/mytest").expanduser()

dev_branch = "mydev"


def setup_repo():
    # git checkout main
    subprocess.run(["git", "checkout", "main"])
    subprocess.run(["git", "reset", "--hard", "origin/main"])

    # delete mydev local and remote branches
    subprocess.run(["git", "branch", "-D", dev_branch])
    subprocess.run(["git", "push", "origin", "--delete", dev_branch])

    # delete all pr's in mytest repo using github api
    prs_json = subprocess.run(
        ["gh", "pr", "list", "--json", "url"], capture_output=True, text=True
    ).stdout

    prs = json.loads(prs_json)

    for pr in prs:
        pr_url = pr["url"]
        subprocess.run(
            ["gh", "pr", "close", pr_url, "-d"], capture_output=True, text=True
        )

    # create new branch mydev
    subprocess.run(["git", "checkout", "main"])
    subprocess.run(["git", "checkout", "-b", "mydev"])


@pytest.mark.parametrize("run_workflows", [True, False])
def test_ghchain(run_workflows):
    os.chdir(my_test_repo)
    setup_repo()

    # change the README.md file 4 times and commit each change
    for i in range(4):
        with open("README.md", "a") as f:
            f.write(f"line {i}\n")
        subprocess.run(["git", "add", "README.md"])
        subprocess.run(["git", "commit", "-m", f"commit {i}"])

    runner = CliRunner()
    result = runner.invoke(cli.main, ["--run-tests" if run_workflows else ""])

    assert result.exit_code == 0


if __name__ == "__main__":
    test_ghchain(True)
