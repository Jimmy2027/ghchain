import os
import subprocess
from collections import defaultdict

import click

import ghchain
from ghchain.utils import logger, run_command


def git_push(branch_name: str):
    try:
        ghchain.repo.git.push("origin", branch_name)
    except Exception as e:
        logger.error(f"Error pushing branch {branch_name}: {e}")
        raise


def parse_git_show_ref(output: str) -> dict:
    """
    Parse the output of 'git show-ref --head --dereference' into a dictionary.

    Parameters:
        output (str): The output string from the 'git show-ref --head --dereference' command.

    Returns:
        dict: A dictionary with commit hashes as keys and lists of reference names as values.
    """
    refs_dict = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue  # skip lines that don't have exactly two parts
        commit_hash, ref_name = parts

        # Skip non-branch references
        if "heads" not in ref_name:
            continue

        if commit_hash not in refs_dict:
            refs_dict[commit_hash] = []
        refs_dict[commit_hash].append(ref_name.replace("refs/heads/", ""))
    return refs_dict


def get_refs_dict() -> dict:
    """
    Return a dictionary of commit hashes and their corresponding branch names.
    """
    result = run_command(["git", "show-ref", "--head", "--dereference"])
    return parse_git_show_ref(result.stdout)


def checkout_branch(branch_name: str):
    run_command(["git", "checkout", branch_name])


def update_branch(branch_name: str):
    return run_command(["git", "pull", "origin", branch_name])


def update_base_branch(base_branch: str):
    """
    Update the base branch with the latest changes from origin
    """
    checkout_branch(base_branch)
    result = update_branch(base_branch)

    if "Already up to date" not in result.stdout:
        click.echo("Changes pulled from origin. Rebasing stack.")
        rebase_onto_target(base_branch)
        return

    run_command(["git", "checkout", "-"])


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


def find_ref_branches_of_commit(refs: dict, commit: str) -> list[str]:
    return refs.get(commit, [])


def find_branches_with_commit(commit: str) -> list[str]:
    branches = run_command(["git", "branch", "--contains", commit])
    branches = [
        branch.replace("*", "").strip()
        for branch in branches.stdout.split("\n")
        if branch
    ]
    return branches


def get_stack(commits: list[str], dev_branch: str) -> list[str]:
    """
    Get the commits that are not in base branch
    Sort the branches by the number of those commits that they contain
    return the sorted list of branches
    """
    stack = defaultdict(int)
    for commit in commits:
        result = run_command(["git", "branch", "--contains", commit])
        branches = result.stdout.split("\n")
        branches = [branch.replace("*", "").strip() for branch in branches if branch]
        branches = [branch for branch in branches if branch != dev_branch]
        if not branches:
            continue
        for branch in branches:
            stack[branch] += 1

    sorted_stack = sorted(stack.items(), key=lambda item: item[1], reverse=True)

    return [branch for branch, _ in sorted_stack]


def local_branch_exists(branch_name):
    result = run_command(["git", "branch", "--list", branch_name])
    return bool(result.stdout.strip())


def create_branch_name(branch_name_template: str, next_pr_id: int):
    # Get the git author name
    author_name = (
        ghchain.repo.config_reader().get_value("user", "name").replace(" ", "_").lower()
    )

    branch_name = branch_name_template.format(
        git_config_author=author_name, pr_id=next_pr_id
    )

    return branch_name


def create_branch_from_commit(branch_name, commit_sha):
    run_command(["git", "branch", branch_name, commit_sha])


def checkout_new_branch(branch_name, commit_sha):
    run_command(["git", "checkout", "-b", branch_name, commit_sha])


def set_upstream_to_origin(branch_name):
    run_command(
        ["git", "branch", "--set-upstream-to", f"origin/{branch_name}", branch_name]
    )


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
