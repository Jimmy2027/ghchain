from dataclasses import dataclass

from ghchain.config import config, logger
from ghchain.git_utils import (
    find_branches_with_commit,
    get_commits_not_in_base_branch,
    get_current_branch,
)


@dataclass
class Stack:
    commits: list[str]
    commit2message: dict[str, str]
    commit2branches: dict[str, set[str]]
    dev_branch: str
    base_branch: str

    @classmethod
    def create(cls, base_branch: str = None):
        if not base_branch:
            base_branch = config.base_branch
        dev_branch = get_current_branch()
        commit2message = {
            e[0]: e[1] for e in get_commits_not_in_base_branch(base_branch)
        }
        commits = list(commit2message)
        commit2branch = {
            commit: set(find_branches_with_commit(commit)) for commit in commits
        }

        logger.info(f"Creating stack with dev branch: {dev_branch}")
        return cls(
            commits,
            commit2message,
            commit2branch,
            dev_branch=dev_branch,
            base_branch=base_branch,
        )

    def commit2branch(self, commit: str) -> str | None:
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
