import re
import subprocess
from collections import defaultdict
from pathlib import Path

from ghchain.utils import run_command


def update_base_branch(base_branch: str):
    """
    Update the base branch with the latest changes from origin
    """
    subprocess.run(["git", "checkout", base_branch])
    subprocess.run(["git", "pull", "origin", base_branch])
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
    result = subprocess.run(
        ["git", "rebase", "--update-refs", branch],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    while any(e in result.stdout for e in ["CONFLICT", "needs merge"]):
        print(
            "Conflicts detected during rebase. Please resolve them and then press Enter to continue."
        )
        input()
        result = subprocess.run(
            ["git", "rebase", "--continue"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env={"GIT_EDITOR": "true"},  # to prevent the editor from opening
        )
    branches = [
        line.strip().replace("refs/heads/", "")
        for line in result.stdout.split("\n")
        if line.strip() and "refs/heads/" in line and not "Successfully rebased" in line
    ]

    # push each branch to origin
    command = ["git", "push", "--force-with-lease", "origin"] + branches
    result = subprocess.run(
        command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True
    )
    print(result.stdout)


def get_stack(commits: list[str]) -> list[str]:
    """
    Get the commits that are not in base branch
    Sort the branches by the number of those commits that they contain
    return the sorted list of branches
    """
    # TODO make sure this works also if one branch has multiple commits
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


def get_commits_not_in_base_branch(base_branch):
    commits = subprocess.getoutput(
        f"git log {base_branch}..HEAD --reverse --format='%H %s'"
    ).splitlines()
    return [line.split(" ", 1) for line in commits]
