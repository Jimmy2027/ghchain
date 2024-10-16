import re
from typing import List, Optional

import pandas as pd
from loguru import logger
from pydantic import BaseModel

import ghchain
from ghchain.git_utils import create_branch_name, get_current_branch, git_push
from ghchain.github_utils import (
    create_pull_request,
    get_next_gh_id,
    get_pr_url_for_branch,
    run_tests_on_pr,
    update_pr_descriptions,
)
from ghchain.status import (
    PrStatus,
    StatusCheck,
    WorkflowStatus,
    mergeable_status_to_ansi,
    review_decision_to_ansi,
)


def status_to_emoji(status: str):
    status_to_emoji_mapping = {
        "success": "✅",
        "failure": "❌",
        "neutral": "⚪",
        "cancelled": "🛑",
        "timed_out": "⏰",
        "in_progress": "🔄",
        "completed": "✅",
    }

    if status in status_to_emoji_mapping:
        return status_to_emoji_mapping[status]
    else:
        return status


def status_check_to_note(status_checks: dict[str, StatusCheck]):
    status_checks_df = pd.DataFrame(
        [
            {
                k: status_to_emoji(v.lower())
                for k, v in status_check.__dict__.items()
                if k in ["name", "conclusion", "status"]
            }
            for status_check in status_checks.values()
        ]
    ).set_index("name")

    return "\n\n[[status_checks]]\n\n" + status_checks_df.to_markdown()


def workflow_statuses_to_note(workflow_statuses: list[WorkflowStatus]):
    workflow_statuses_df = pd.DataFrame(
        [
            {
                k: status_to_emoji(v)
                for k, v in ws.to_dict().items()
                if k in {"status", "conclusion", "name"}
            }
            for ws in workflow_statuses
        ]
    ).set_index("name")
    return "\n\n[[workflow_statuses]]\n\n" + workflow_statuses_df.to_markdown()


def get_commit_notes(pr_url: str, pr_status: PrStatus):
    notes_str = f"[ghchain]\npr url = {pr_url}\n"
    if not pr_status:
        return notes_str
    notes_str += (
        f"Review Decision = {review_decision_to_ansi(pr_status.review_decision)}\n"
    )
    notes_str += f"Mergable = {mergeable_status_to_ansi(pr_status.is_mergeable)}\n"
    notes_str += "\n".join(
        [
            f"{key} = {value}"
            for key, value in pr_status.to_dict().items()
            if key in ["is_draft", "title"]
        ]
    )

    # convert workflow_statuses to a markdonw table
    if pr_status.workflow_statuses:
        notes_str += workflow_statuses_to_note(pr_status.workflow_statuses)
    if pr_status.status_checks:
        notes_str += status_check_to_note(pr_status.status_checks)

    return notes_str


class Commit(BaseModel):
    """
    Commit object with sha, message, branch, pr_url, notes, and pr_status.
    It is expected that every non-fixup commit has its corresponding branch.
    """

    sha: str
    message: str
    branch: str | None = None
    pr_url: Optional[str] = None
    notes: Optional[str] = None
    pr_status: Optional[PrStatus] = None

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, **data):
        super().__init__(**data)
        if not self.branch:
            return

        self.pr_status = PrStatus.from_branchname(self.branch)

        if not self.pr_url:
            self.pr_url = get_pr_url_for_branch(self.branch)

        # Fetch and parse commit notes
        self.notes = get_commit_notes(self.pr_url, self.pr_status)

        self.update_notes()

    def update_notes(self):
        # Write the updated notes back to the git notes

        ghchain.repo.git.notes("add", "-f", "-m", self.notes, self.sha)

    @property
    def pr_id(self) -> Optional[int]:
        if not self.pr_url:
            return None
        return int(self.pr_url.rstrip("/").split("/")[-1])

    @property
    def is_fixup(self) -> bool:
        return self.message.startswith("fixup!") or self.message.startswith("squash!")


class Stack(BaseModel):
    commits: List[Commit]
    dev_branch: str
    base_branch: str

    @classmethod
    def create(cls, base_branch: Optional[str] = None) -> "Stack":
        """
        Create a Stack object with commits from the current branch which are not in the base branch.
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
        # Reverse log output to start from the bottom of the stack
        for line in log_output[::-1]:
            match = log_pattern.match(line)
            if match:
                sha = match.group("sha")
                branches = (
                    match.group("branches")
                    .replace("HEAD -> ", "")
                    .replace("origin/", "")
                    .split(", ")
                )
                message = match.group("message")

                # Remove the dev branch from the list of branches
                branches = set(branches) - {dev_branch}
                if len(branches) > 1:
                    error_message = f"Commit {sha} has multiple branches: {branches}. This is not supported."
                    logger.error(error_message)
                    raise ValueError(error_message)

                branch = branches.pop() if branches else None
                commit = Commit(
                    sha=sha,
                    branch=branch,
                    message=message,
                )
                commits.append(commit)
                if commit.is_fixup:
                    # Find the previous commit that is not a fixup and mark it with the same branch
                    target_commit = next(
                        (
                            commit
                            for commit in commits[::-1]
                            if not commit.is_fixup and not commit.branch
                        ),
                        None,
                    )
                    if target_commit:
                        target_commit.branch = commits[-1].branch

            else:
                # If the line doesn't match the pattern, it might be a commit without branches
                parts = line.split(" ", 1)
                sha = parts[0]
                message = parts[1]
                commits.append(Commit(sha=sha, branch=None, message=message))

        return cls(commits=commits, dev_branch=dev_branch, base_branch=base_branch)

    @property
    def commit2idx(self):
        return {commit.sha: i for i, commit in enumerate(self.commits)}

    @property
    def branch_ids(self) -> set[int]:
        return {
            int(commit.branch.split("-")[-1])
            for commit in self.commits
            if commit and commit.branch
            if commit.branch.split("-")[-1].isnumeric()
        }

    @property
    def branches(self) -> list[str]:
        """
        Return the branches in the stack, sorted by order in the stack.
        """
        return [commit.branch for commit in self.commits if commit.branch]

    def process_commit(
        self,
        commit: Commit,
        create_pr: bool = False,
        draft: bool = False,
        with_tests: bool = False,
    ):
        """
        Create a branch for each commit in the stack that doesn't already have one.
        If create_pr is True, create a PR for each branch.
        """
        pr_created = False
        if not commit.branch:
            branch_id = max([get_next_gh_id(), *[id + 1 for id in self.branch_ids]])
            branch_name = create_branch_name(
                ghchain.config.branch_name_template, branch_id
            )
            logger.info(f"Creating branch {branch_name} for commit {commit.sha}")
            ghchain.repo.git.branch(branch_name, commit.sha)
            commit.branch = branch_name

            # Push the branch to the remote
            git_push(branch_name)
        else:
            branch_name = commit.branch

        # If the commit is not a fixup and it does not have a PR, create one
        if not commit.is_fixup and create_pr and not commit.pr_id:
            commit.pr_url = create_pull_request(
                base_branch=ghchain.config.base_branch.replace("origin/", "")
                if not self.commit2idx[commit.sha]
                else self.commits[self.commit2idx[commit.sha] - 1].branch,
                head_branch=branch_name,
                title=commit.message.split("\n")[0],
                body=commit.message,
                draft=draft,
            )
            pr_created = True

        if create_pr:
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
