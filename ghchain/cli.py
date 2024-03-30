"""Console script for ghchain."""

import subprocess

import click

from ghchain.config import Config
from ghchain.git_utils import (
    create_branch_name,
    get_commits_not_in_base_branch,
    get_git_base_dir,
    local_branch_exists,
    rebase_onto_branch,
    update_base_branch,
)
from ghchain.github_utils import (
    create_pull_request,
    get_pr_url_for_branch,
    update_pr_descriptions,
)

pr_stack = []


@click.command()
@click.option(
    "--default-base-branch",
    default="main",
    help="Default base branch for the first PR.",
)
@click.option("--draft", is_flag=True, help="Create the pull request as a draft.")
@click.option(
    "--run-tests",
    is_flag=True,
    help="Run the github workflows that are specified in the .ghchain.toml config of the repository.",
)
@click.option(
    "--all-tests",
    is_flag=True,
    help=(
        "Run the github workflows that are specified in the .ghchain.toml "
        "config of the repository for all PR's in the stack."
    ),
)
@click.option("--rebase-onto", default=None)
def main(default_base_branch, draft, run_tests, all_tests, rebase_onto):
    """
    From your dev branch, gather all commits that are not in the default base branch (main).
    For each commit, create a new branch based on the previous branch with the next commit,
      push the branch to origin and create a PR.

    How to:
    Update a commit in the stack: git commit --amend --no-edit on the branch with the commit.
    Then from your dev branch, run `ghchain --rebase-onto <branch>`
    """
    if rebase_onto:
        rebase_onto_branch(rebase_onto)
        return

    base_branch = default_base_branch
    update_base_branch(base_branch)

    config = Config.from_toml(get_git_base_dir() / ".ghchain.toml")
    commits = get_commits_not_in_base_branch(base_branch=default_base_branch)
    if not commits:
        click.echo("No commits found that are not in main.")
        return

    for commit_sha, commit_msg in commits:
        click.echo(f"Processing commit: {commit_sha} - {commit_msg}")
        branch_name = create_branch_name(commit_msg)

        subprocess.run(["git", "checkout", base_branch])
        subprocess.run(["git", "pull", "origin", base_branch])
        if local_branch_exists(branch_name):
            click.echo(
                f"Local branch '{branch_name}' already exists. Checking for existing PR..."
            )
            pr_url = get_pr_url_for_branch(branch_name)
            if not pr_url:
                click.echo(
                    f"No open PR found for branch '{branch_name}'. You may need to create a PR manually."
                )
                continue
        else:
            # ask user to continue with branch name
            if not click.confirm(
                f"Create a new branch '{branch_name}' for this commit?", default=True
            ):
                continue
            subprocess.run(["git", "checkout", "-b", branch_name, commit_sha])
            subprocess.run(["git", "push", "origin", branch_name])
            subprocess.run(
                [
                    "git",
                    "branch",
                    "--set-upstream-to",
                    f"origin/{branch_name}",
                    branch_name,
                ]
            )
            pr_url = create_pull_request(
                config,
                base_branch,
                branch_name,
                branch_name,
                commit_msg,
                draft,
                run_tests,
            )
        if pr_url:
            pr_stack.append(pr_url)
            update_pr_descriptions(
                config=config,
                run_tests=(pr_url, branch_name) if run_tests and all_tests else None,
                pr_stack=pr_stack,
            )
            base_branch = branch_name
        if not click.confirm(
            "Do you want to continue with the next commit?", default=True
        ):
            break
        subprocess.run(["git", "checkout", default_base_branch])
