import json
import os
import subprocess

import pytest
from click.testing import CliRunner

from ghchain.config import CONFIG_FN, config, get_git_base_dir, logger
from ghchain.git_utils import get_all_branches


@pytest.fixture
def cli_runner():
    runner = CliRunner()
    with runner.isolated_filesystem():
        yield runner


# @pytest.fixture(scope="module")
# def repo_cleanup():
#     """Fixture to clean up the repository before tests."""
#     cleanup_repo()
#     yield
#     cleanup_repo()


def cleanup_repo():
    """Delete all current branches and pull requests and create a new branch mydev."""
    subprocess.run(["git", "checkout", "main"])
    subprocess.run(["git", "reset", "--hard", "origin/main"])

    branches = set(get_all_branches()) - {"main"}

    for branch in branches:
        subprocess.run(["git", "branch", "-D", branch])
        subprocess.run(["git", "push", "origin", "--delete", branch])

    prs_json = subprocess.run(
        ["gh", "pr", "list", "--json", "url"], capture_output=True, text=True
    ).stdout

    prs = json.loads(prs_json)
    for pr in prs:
        pr_url = pr["url"]
        subprocess.run(
            ["gh", "pr", "close", pr_url, "-d"], capture_output=True, text=True
        )

    subprocess.run(["git", "checkout", "main"])
    subprocess.run(["git", "checkout", "-b", "mydev"])


def create_stack():
    """Change the README.md file 4 times and commit each change."""
    for i in range(4):
        with open("README.md", "a") as f:
            f.write(f"line {i}\n")
        subprocess.run(["git", "add", "README.md"])
        subprocess.run(["git", "commit", "-m", f"commit {i}"])


def test_cwd():
    """Test that the current working directory is in 'mytest'."""
    assert os.getcwd().endswith("mytest")


@pytest.mark.parametrize("run_workflows", [True, False])
def test_create_stack(cli_runner, repo_cleanup, run_workflows):
    with cli_runner.isolated_filesystem():
        logger.info(f"Current working directory: {os.getcwd()}")
        logger.info(f"Current directory files: {os.listdir()}")

        completed_process = subprocess.run(
            ["git", "clone", "https://github.com/HendrikKlug-synthara/mytest.git", "."],
            capture_output=True,
            text=True,
        )

        logger.info("Standard Output:", completed_process.stdout)
        logger.info("Standard Error:", completed_process.stderr)

        os.chdir("mytest")

        logger.info("Running test_create_stack")
        logger.info(f"Loaded config from {CONFIG_FN}")
        logger.info(f"Config: {config.to_dict()}")
        logger.info(f"Current working directory: {os.getcwd()}")
        logger.info(f"Current directory files: {os.listdir()}")
        logger.info(f"Git base dir: {get_git_base_dir()}")
        # create_stack()

        # if run_workflows:
        #     result = cli_runner.invoke(cli.process_commits, ["--with-tests"])
        # else:
        #     result = cli_runner.invoke(cli.process_commits)

        # assert result.exit_code == 0
