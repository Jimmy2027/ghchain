import json
import os
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from ghchain import cli
from ghchain.config import Config, logger
from ghchain.git_utils import get_all_branches
from ghchain.utils import run_command


@pytest.fixture(scope="session")
def setup_mytest_repo(tmpdir_factory):
    temp_dir = tmpdir_factory.mktemp("shared_temp_dir")
    os.chdir(temp_dir)
    logger.info(f"Current working directory: {os.getcwd()}")
    subprocess.run(
        ["git", "clone", "https://github.com/HendrikKlug-synthara/mytest.git", "."],
        capture_output=True,
        text=True,
        cwd=os.getcwd(),
        check=True,
    )

    assert "GH_TOKEN" in os.environ
    command = (
        f"git remote set-url origin "
        f"https://x-access-token:{os.environ['GH_TOKEN']}@"
        f"github.com/HendrikKlug-synthara/mytest.git"
    )
    subprocess.run(command, shell=True, check=True)

    logger.info("Configuring git user")
    global config
    config_fn = Path(".ghchain.toml").absolute()
    logger.info(f"Config file: {config_fn}")
    assert config_fn.exists(), f"Config file {config_fn} does not exist."
    config = Config.from_toml(config_fn)
    return temp_dir


@pytest.fixture
def cli_runner(setup_mytest_repo):
    runner = CliRunner()
    yield runner, setup_mytest_repo


@pytest.fixture(scope="module")
def repo_cleanup():
    """Fixture to clean up the repository before tests."""
    cleanup_repo()
    yield


def cleanup_repo():
    """Delete all current branches and pull requests and create a new branch mydev."""
    run_command(["git", "checkout", "main"])
    run_command(["git", "reset", "--hard", "origin/main"])

    branches = set(get_all_branches()) - {"main"}

    for branch in branches:
        run_command(["git", "branch", "-D", branch])
        run_command(["git", "push", "origin", "--delete", branch])

    prs_json = run_command(
        ["gh", "pr", "list", "--json", "url"],
    ).stdout

    prs = json.loads(prs_json)
    for pr in prs:
        pr_url = pr["url"]
        run_command(
            ["gh", "pr", "close", pr_url, "-d"],
        )

    run_command(["git", "checkout", "main"])
    run_command(["git", "checkout", "-b", "mydev"])


def create_stack():
    """Change the README.md file 4 times and commit each change."""
    for i in range(4):
        with open("README.md", "a") as f:
            f.write(f"line {i}\n")
        run_command(["git", "add", "README.md"])
        run_command(["git", "commit", "-m", f"commit {i}"])


@pytest.mark.parametrize("run_workflows", [False, True])
def test_create_stack(cli_runner, repo_cleanup, run_workflows):
    cli_runner, _ = cli_runner

    create_stack()

    if run_workflows:
        result = cli_runner.invoke(cli.process_commits, ["--with-tests"])
    else:
        result = cli_runner.invoke(cli.process_commits)

    # assert that the repo has 4 open pull requests
    prs = run_command(["gh", "pr", "list", "--json", "url"]).stdout
    prs = json.loads(prs)
    assert len(prs) == 4, f"Expected 4 pull requests, got {len(prs)}"

    assert result.exit_code == 0


if __name__ == "__main__":
    pytest.main(["-v", __file__, "-s"])
