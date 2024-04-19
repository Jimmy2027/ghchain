from dataclasses import dataclass
import os
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Optional, Union

import click

from ghchain.utils import run_command


def get_all_branches() -> list[str]:
    result = subprocess.run(["git", "branch"], stdout=subprocess.PIPE, text=True)
    branches = result.stdout.splitlines()
    # Remove the leading '*' from the current branch and strip leading/trailing whitespace
    branches = [branch.replace("*", "").strip() for branch in branches]
    return branches


def git_push(branch_name: str):
    subprocess.run(["git", "push", "origin", branch_name])


def checkout_branch(branch_name: str):
    subprocess.run(["git", "checkout", branch_name])


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
        rebase_onto_branch(base_branch)
        return

    subprocess.run(["git", "checkout", "-"])


def rebase_onto_branch(branch: str):
    result = run_command(
        ["git", "rebase", "--update-refs", branch],
    )

    click.echo(f"Rebase command output: {result.stdout} {result.stderr}")

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
    print(f"Pushing branches: {branches}")
    command = ["git", "push", "--force-with-lease", "origin"] + branches
    result = run_command(command, check=True)
    print(f"{result.stdout}\n{result.stderr}")


def update_stack(commits: list[str]) -> list[str]:
    """
    Update the stack with the new commits
    """
    stack = get_stack(commits)
    stack.append("main")

    stack_top = stack.pop(0)

    for branch in stack:
        subprocess.run(["git", "checkout", branch])
        subprocess.run(["git", "pull", "origin", branch])

        subprocess.run(["git", "checkout", stack_top])
        result = subprocess.run(
            ["git", "rebase", "--update-refs", branch],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if "fatal" in result.stdout:
            print(
                "Conflicts detected during rebase. Please resolve them and then press Enter to continue."
            )
            input()

    for branch in stack:
        subprocess.run(["git", "checkout", branch])
        subprocess.run(["git", "push", "--force-with-lease", "origin", branch])


def get_git_base_dir() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], stdout=subprocess.PIPE, text=True
    )
    return Path(result.stdout.strip())


def find_branches_with_commit(commit: str) -> list[str]:
    branches = run_command(["git", "branch", "--contains", commit])
    branches = [
        branch.replace("*", "").strip()
        for branch in branches.stdout.split("\n")
        if branch
    ]
    return branches


@dataclass
class Stack:
    commits: list[str]
    commit2message: dict[str, str]
    commit2branches: dict[str, set[str]]
    dev_branch: str
    base_branch: str = "main"

    @classmethod
    def create(cls, base_branch: str):
        dev_branch = get_current_branch()
        commit2message = {
            e[0]: e[1] for e in get_commits_not_in_base_branch(base_branch)
        }
        commits = list(commit2message)
        commit2branch = {
            commit: set(find_branches_with_commit(commit)) for commit in commits
        }

        return cls(commits, commit2message, commit2branch, dev_branch=dev_branch)

    def commit2branch(self, commit: str) -> Optional[str]:
        # return the branch for which the commit is the latest commit
        return next(
            (
                branch
                for branch, commits in self.branch2commits.items()
                if commit == commits[-1]
            ),
            None,
        )

    @property
    def branch2commits(self) -> dict[str, list[str]]:
        return {
            branch: get_commits_not_in_base_branch(
                self.base_branch, target_branch=branch, only_sha=True
            )
            for branch in set(
                b for branches in self.commit2branches.values() for b in branches
            )
        }

    @property
    def branches(self) -> list[str]:
        branch_commit_counts = {
            branch: len(commits) for branch, commits in self.branch2commits.items()
        }
        sorted_branches = sorted(
            branch_commit_counts, key=branch_commit_counts.get, reverse=True
        )

        return sorted_branches

    @property
    def commits_without_branch(self) -> list[str]:
        return [
            commit
            for commit, branches in self.commit2branches.items()
            if not (branches - {self.dev_branch})
        ]


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
    author_name = subprocess.getoutput("git config user.name").replace(" ", "_").lower()

    branch_name = branch_name_template.format(
        git_config_author=author_name, pr_id=next_pr_id
    )

    return branch_name


def get_commits_not_in_base_branch(
    base_branch, ignore_fixup=True, target_branch="HEAD", only_sha=False
) -> Union[list[str], list[list[str]]]:
    commits = subprocess.getoutput(
        f"git log {base_branch}..{target_branch} --reverse --format='%H %s'"
    ).splitlines()
    if ignore_fixup:
        commits = [
            line.split(" ", 1)
            for line in commits
            if not line.split(" ", 1)[1].startswith("fixup!")
        ]
    else:
        commits = [line.split(" ", 1) for line in commits]

    if only_sha:
        return [commit[0] for commit in commits]
    else:
        return commits


def checkout_new_branch(branch_name, commit_sha):
    run_command(["git", "checkout", "-b", branch_name, commit_sha])


def set_upstream_to_origin(branch_name):
    run_command(
        ["git", "branch", "--set-upstream-to", f"origin/{branch_name}", branch_name]
    )


def get_current_branch() -> str:
    result = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    return result.stdout.strip()
