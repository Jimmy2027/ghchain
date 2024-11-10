from typing import Optional

from pydantic import BaseModel

import ghchain
from ghchain.github_utils import get_pr_url_for_branch
from ghchain.stack import get_commit_notes
from ghchain.status import PrStatus, WorkflowStatus


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
    workflow_statuses: Optional[list[WorkflowStatus]] = None

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, **data):
        super().__init__(**data)

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
            workflow_statuses=self.workflow_statuses,
        )

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
