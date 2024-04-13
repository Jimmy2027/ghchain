import os
import re
import subprocess
from collections import defaultdict
from pathlib import Path

import click

from ghchain.utils import run_command


def git_push(branch_name: str):
    subprocess.run(["git", "push", "origin", branch_name])


def checkout_branch(branch_name: str):
    subprocess.run(["git", "checkout", branch_name])


def update_branch(branch_name: str):
    subprocess.run(["git", "pull", "origin", branch_name])


def update_base_branch(base_branch: str):
    """
    Update the base branch with the latest changes from origin
    """
    checkout_branch(base_branch)
    update_branch(base_branch)
    subprocess.run(["git", "checkout", "-"])


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


def rebase_onto_branch(branch: str):
    result = run_command(
        ["git", "rebase", "--update-refs", branch],
    )

    click.echo(f"Rebase command output: {result.stdout}")

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
    print(f"{ result.stdout }\n{ result.stderr }")


def get_stack(commits: list[str]) -> list[str]:
    """
    Get the commits that are not in base branch
    Sort the branches by the number of those commits that they contain
    return the sorted list of branches
    """
    stack = defaultdict(int)
    for commit in commits:
        result = run_command(["git", "branch", "--contains", commit])
        branches = result.stdout.split("\n")
        for branch in branches:
            if branch:
                stack[branch.replace("*", "").strip()] += 1

    sorted_stack = sorted(stack.items(), key=lambda item: item[1], reverse=True)

    return [branch for branch, _ in sorted_stack]


def local_branch_exists(branch_name):
    result = run_command(["git", "branch", "--list", branch_name])
    return bool(result.stdout.strip())


def create_branch_name(commit_message):
    sanitized = re.sub(r"[^a-zA-Z0-9 ]", "", commit_message.lower())
    return re.sub(r"\s+", "_", sanitized)[:30]


def get_commits_not_in_base_branch(base_branch, ignore_fixup=True):
    commits = subprocess.getoutput(
        f"git log {base_branch}..HEAD --reverse --format='%H %s'"
    ).splitlines()
    if ignore_fixup:
        return [
            line.split(" ", 1)
            for line in commits
            if not line.split(" ", 1)[1].startswith("fixup!")
        ]
    else:
        return [line.split(" ", 1) for line in commits]


def checkout_new_branch(branch_name, commit_sha):
    run_command(["git", "checkout", "-b", branch_name, commit_sha])


def set_upstream_to_origin(branch_name):
    run_command(
        ["git", "branch", "--set-upstream-to", f"origin/{branch_name}", branch_name]
    )


def get_current_branch() -> str:
    result = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    return result.stdout.strip()
