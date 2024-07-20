from typing import List, Optional, Set, Union

from git import GitCommandError, Repo
from loguru import logger
from pydantic import BaseModel

from ghchain.config import config

repo = Repo(".")


def find_branches_with_commit(commit: str) -> List[str]:
    """
    Find branches containing the specified commit.
    """
    try:
        branches = repo.git.branch("--contains", commit).split("\n")
        branches = [branch.replace("*", "").strip() for branch in branches if branch]
        return branches
    except GitCommandError as e:
        logger.error(f"Error finding branches with commit {commit}: {e}")
        raise


def get_commits_not_in_base_branch(
    base_branch: str,
    ignore_fixup: bool = True,
    target_branch: str = "HEAD",
    only_sha: bool = False,
) -> Union[List[str], List[List[str]]]:
    """
    Get the list of commits not in the base branch.
    """
    try:
        commits = repo.git.log(
            f"{base_branch}..{target_branch}", "--reverse", "--format=%H %s"
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
    except GitCommandError as e:
        logger.error(f"Error getting commits: {e}")
        raise


def get_current_branch() -> str:
    """
    Get the current branch name.
    """
    try:
        return repo.active_branch.name
    except TypeError as e:
        logger.error(f"Error getting current branch: {e}")
        raise


class Commit(BaseModel):
    sha: str
    message: str
    branches: Set[str]
    pr_id: Optional[int] = None


class Stack(BaseModel):
    commits: List[Commit]
    dev_branch: str
    base_branch: str

    @classmethod
    def create(cls, base_branch: Optional[str] = None) -> "Stack":
        """
        Create a Stack object with commits from the current branch not in the base branch.
        """
        if not base_branch:
            base_branch = config.base_branch
        dev_branch = get_current_branch()
        commit2message = {
            e[0]: e[1] for e in get_commits_not_in_base_branch(base_branch)
        }
        commits = list(commit2message.keys())
        commit2branch = {
            commit: set(find_branches_with_commit(commit)) for commit in commits
        }

        logger.info(f"Creating stack with dev branch: {dev_branch}")

        commit_objects = [
            Commit(sha=sha, message=message, branches=branches)
            for sha, message, branches in zip(
                commits, commit2message.values(), commit2branch.values()
            )
        ]
        return cls(
            commits=commit_objects, dev_branch=dev_branch, base_branch=base_branch
        )
