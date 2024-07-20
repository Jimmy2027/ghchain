import re
from typing import List, Optional, Set, Union

from git import GitCommandError
from loguru import logger
from pydantic import BaseModel

import ghchain
from ghchain.git_utils import create_branch_name, git_push
from ghchain.github_utils import (
    create_pull_request,
    get_next_gh_id,
    run_tests_on_pr,
    update_pr_descriptions,
)


def find_branches_with_commit(commit: str) -> List[str]:
    """
    Find branches containing the specified commit.
    """
    try:
        branches = ghchain.repo.git.branch("--contains", commit).split("\n")
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
        commits = ghchain.repo.git.log(
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
        return ghchain.repo.active_branch.name
    except TypeError as e:
        logger.error(f"Error getting current branch: {e}")
        raise


class Commit(BaseModel):
    sha: str
    message: str
    branches: Set[str]
    pr_url: Optional[str] = None

    @property
    def pr_id(self) -> Optional[int]:
        if not self.pr_url:
            return None
        return int(self.pr_url.split("/")[-1])


class Stack(BaseModel):
    commits: List[Commit]
    dev_branch: str
    base_branch: str

    @classmethod
    def create(cls, base_branch: Optional[str] = None) -> "Stack":
        """
        Create a Stack object with commits from the current branch not in the base branch.
        Whatever branch is currently checked out will be considered the dev branch.
        """
        if not base_branch:
            base_branch = ghchain.config.base_branch
        dev_branch = get_current_branch()

        logger.debug(f"Creating stack with dev branch: {dev_branch}")

        log_output = ghchain.repo.git.log(
            f"{base_branch}..", "--decorate", "--pretty=oneline"
        ).splitlines()

        # Regular expression to match the git log output
        log_pattern = re.compile(
            r"(?P<sha>[a-f0-9]{40}) \((?P<branches>[^)]+)\) (?P<message>.+)"
        )

        commits = []
        for line in log_output:
            match = log_pattern.match(line)
            if match:
                sha = match.group("sha")
                branches = match.group("branches").replace("HEAD -> ", "").split(", ")
                message = match.group("message")

                # remove the dev branch from the list of branches
                branches = set(branches) - {dev_branch}
                commits.append(Commit(sha=sha, branches=branches, message=message))
            else:
                # If the line doesn't match the pattern, it might be a commit without branches
                parts = line.split(" ", 1)
                sha = parts[0]
                message = parts[1]
                commits.append(Commit(sha=sha, branches=set(), message=message))

        return cls(commits=commits, dev_branch=dev_branch, base_branch=base_branch)

    @property
    def commit2idx(self):
        return {commit.sha: i for i, commit in enumerate(self.commits)}

    @property
    def branch_ids(self) -> set[int]:
        return {
            int(b.split("-")[-1])
            for commit in self.commits
            if commit and commit.branches
            for b in commit.branches
            if b.split("-")[-1].isnumeric()
        }

    @property
    def branches(self) -> list[str]:
        """
        Return the branches in the stack, sorted by order in the stack.
        """
        return [
            branch
            for commit in self.commits
            if commit.branches
            for branch in commit.branches
            if "origin/" not in branch
        ]

    def process_commit(
        self,
        commit: Commit,
        publish: bool = False,
        draft: bool = False,
        with_tests: bool = False,
    ):
        """
        Create a branch for each commit in the stack that doesn't already have one.
        If publish is True, create a PR for each branch.
        """
        pr_created = False
        if not commit.branches:
            branch_id = max([get_next_gh_id(), *[id + 1 for id in self.branch_ids]])
            branch_name = create_branch_name(
                ghchain.config.branch_name_template, branch_id
            )
            logger.info(f"Creating branch {branch_name} for commit {commit.sha}")
            ghchain.repo.git.branch(branch_name, commit.sha)
            commit.branches.add(branch_name)

            # push the branch to the remote
            git_push(branch_name)

            # Update branches for all previous commits in the stack
            for predecessor_commit in self.commits[: self.commit2idx[commit.sha]]:
                predecessor_commit.branches.add(branch_name)

        if publish and not commit.pr_id:
            commit.pr_url = create_pull_request(
                base_branch=ghchain.config.base_branch.replace("origin/", ""),
                head_branch=branch_name,
                title=commit.message,
                body=commit.message,
                draft=draft,
            )
            pr_created = True

        if publish:
            update_pr_descriptions(
                pr_stack=[
                    c.pr_url
                    for c in self.commits[: self.commit2idx[commit.sha] + 1]
                    if c.pr_url
                ]
            )

        if with_tests:
            run_tests_on_pr(branch_name, commit.pr_url)

        return pr_created
