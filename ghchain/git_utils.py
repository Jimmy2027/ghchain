import os
import subprocess

import click

import ghchain
from ghchain.utils import logger, run_command


def git_push(branch_name: str):
    try:
        ghchain.repo.git.push("origin", branch_name)
    except Exception as e:
        logger.error(f"Error pushing branch {branch_name}: {e}")
        raise


def rebase_onto_target(target: str, interactive: bool = False) -> None:
    """
    Rebase the current branch onto a specified target branch or commit hash.

    This function rebases the current branch onto the target specified by the `target` parameter.
    If the `interactive` parameter is set to True, the rebase will be performed interactively.

    Args:
        target (str): The target branch or commit hash to rebase onto.
        interactive (bool, optional): Flag to perform an interactive rebase. Defaults to False.

    The function executes the rebase command using subprocess. If the rebase is interactive, it constructs
    the command accordingly and executes it with `shell=True`. In case of non-interactive rebase, it calls
    `run_command` with the constructed command.

    During the rebase, if conflicts are detected (indicated by "CONFLICT" or "needs merge" in the command output),
    the user is prompted to resolve them. After resolving conflicts, pressing Enter continues the rebase process.

    After a successful rebase, the function extracts the names of branches that were rebased (if any are reported
    in the stderr output) and pushes them to the remote repository using `--force-with-lease` to ensure safety.

    Note:
        - The `GIT_EDITOR` environment variable is set to "true" to prevent the editor from opening during
          `git rebase --continue`

    """
    rebase_command = ["git", "rebase", "--update-refs", target]
    if interactive:
        rebase_command.insert(2, "--interactive")
        rebase_command = " ".join(rebase_command)
        result = subprocess.run(
            rebase_command, shell=True, stderr=subprocess.PIPE, text=True
        )

    else:
        # don't check because otherwise it raises an error when there are conflicts
        result = run_command(rebase_command, shell=interactive, check=False)

    click.echo(f"Rebase command output: {result.stdout} {result.stderr}")

    if result.stdout:
        while any(e in result.stdout for e in ["CONFLICT", "needs merge"]):
            click.echo(
                "Conflicts detected during rebase. Please resolve them and then press Enter to continue."
            )
            input()
            result = run_command(
                ["git", "rebase", "--continue"],
                env={
                    **os.environ,
                    "GIT_EDITOR": "true",
                },  # to prevent the editor from opening
                check=False,
            )
            print(f"Rebase command output: {result.stdout}\n{result.stderr}")

    branches = [
        line.strip().replace("refs/heads/", "")
        for line in result.stderr.split("\n")
        if line.strip() and "refs/heads/" in line and "Successfully rebased" not in line
    ]

    # push each branch to origin
    logger.info(f"Pushing branches: {branches}")
    command = ["git", "push", "--force-with-lease", "origin"] + branches
    run_command(command, check=True)


def create_branch_name(branch_name_template: str, next_pr_id: int):
    # Get the git author name
    author_name = (
        ghchain.repo.config_reader().get_value("user", "name").replace(" ", "_").lower()
    )

    branch_name = branch_name_template.format(
        git_config_author=author_name, pr_id=next_pr_id
    )

    return branch_name


def get_current_branch() -> str:
    """
    Get the current branch name.
    """
    try:
        return ghchain.repo.active_branch.name
    except TypeError as e:
        ghchain.logger.error(f"Error getting current branch: {e}")
        raise


def get_all_branches(remote: bool = False) -> list[str]:
    """
    Get all branches in the repository.
    """
    if remote:
        return get_all_remote_branches()
    return [branch.name for branch in ghchain.repo.branches]


def get_all_remote_branches() -> list[str]:
    """
    Get all remote branches in the repository.
    """
    remote_branches = []
    for remote in ghchain.repo.remotes:
        for branch in remote.refs:
            if "HEAD" not in branch.name:
                remote_branches.append(branch.name.replace(f"{remote.name}/", ""))
    return remote_branches


def get_commit_message_to_branch_mapping() -> dict[str, str]:
    """
    Get a mapping of commit messages to branch names.

    This function returns a dictionary where the keys are commit messages and the values are the branch names
    that contain the corresponding commit.

    Returns:
        dict[str, str]: A dictionary mapping commit messages to branch names.
    """
    return {
        branch.commit.message.replace("\n", ""): branch.name
        for branch in ghchain.repo.branches
    }


def get_issue_url(issue_id: int) -> str:
    """
    Get the GitHub issue URL using the issue ID and the remote repository URL.
    """
    remote_url = ghchain.repo.remotes.origin.url

    # Extract the owner and repo name from the remote URL
    splits = remote_url.split("/")
    owner, repo_name = splits[-2].split(":")[-1], splits[-1].replace(".git", "")

    # Construct the issue URL
    issue_url = f"https://github.com/{owner}/{repo_name}/issues/{issue_id}"

    return issue_url
