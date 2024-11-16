import re
from typing import Optional

import pandas as pd
from pydantic import BaseModel

import ghchain
from ghchain.git_utils import get_issue_url
from ghchain.github_utils import get_pr_url_for_branch
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


def get_commit_notes(
    pr_url: str | None = None,
    pr_status: PrStatus | None = None,
    issue_url: str | None = None,
    workflow_statuses: list[WorkflowStatus] | None = None,
):
    if issue_url:
        return f"[ghchain]\nissue = {issue_url}\n"
    if not pr_status and not pr_url and not workflow_statuses:
        return ""

    notes_str = f"[ghchain]\npr url = {pr_url}\n"
    if pr_status:
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
    if workflow_statuses:
        notes_str += workflow_statuses_to_note(workflow_statuses)
    if pr_status and pr_status.status_checks:
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
    # if the commit is linked to an issue:
    issue_url: str | None = None
    pr_url: Optional[str] = None
    notes: Optional[str] = None
    pr_status: Optional[PrStatus] = None
    workflow_statuses: Optional[list[WorkflowStatus]] = None

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, **data):
        super().__init__(**data)

        # check if the commit meesage contains the github issue id in the following format: [#1234]
        # if it does, set the issue_id to 1234
        pattern = re.compile(r"\[#(\d+)\]")
        match = pattern.search(self.message)

        if match:
            issue_id = int(match.group(1))
            self.issue_url = get_issue_url(issue_id)

        self.workflow_statuses = []
        for workflow in ghchain.config.workflows:
            workflow_status = WorkflowStatus.from_commit_id(
                workflow, commit_id=data["sha"]
            )
            if workflow_status:
                self.workflow_statuses.append(workflow_status)

        if self.branch:
            self.pr_status = PrStatus.from_branchname(self.branch)

            if not self.pr_url:
                self.pr_url = get_pr_url_for_branch(self.branch)

        # Fetch and parse commit notes
        self.notes = get_commit_notes(
            pr_url=self.pr_url,
            pr_status=self.pr_status,
            issue_url=self.issue_url,
            workflow_statuses=self.workflow_statuses,
        )

        self.update_notes()

    def update_notes(self):
        # Write the updated notes back to the git notes

        if self.notes:
            ghchain.repo.git.notes("add", "-f", "-m", self.notes, self.sha)

    @property
    def pr_id(self) -> Optional[int]:
        if not self.pr_url:
            return None
        return int(self.pr_url.rstrip("/").split("/")[-1])

    @property
    def is_fixup(self) -> bool:
        return self.message.startswith("fixup!") or self.message.startswith("squash!")
