import re
import subprocess
from typing import Optional

import pandas as pd
from pydantic import BaseModel, Field

import ghchain
from ghchain.git_utils import get_issue_url
from ghchain.pull_request import PR
from ghchain.status import (
    PrStatus,
    StatusCheck,
    WorkflowStatus,
    mergeable_status_to_ansi,
    review_decision_to_ansi,
)

PR_TRAILER_KEY = "PR"
_PR_TRAILER_VALUE_RE = re.compile(r"^#(\d+)$")
_PR_TRAILER_LINE_RE = re.compile(r"^PR: #\d+\s*$")
# Trailing ` (#N)` PR reference appended to commit titles, GitHub
# squash-merge style. The leading whitespace is required so that
# `(#42)` is not parsed as a PR ref when it abuts other text.
_TITLE_PR_REF_RE = re.compile(r"\s\(#(\d+)\)\s*$")


def strip_pr_trailer(message: str) -> str:
    """Return `message` with any trailing `PR: #N` trailer lines removed.

    Used by `ghchain fix-refs` to match local commits against remote
    branch tips mid-migration — some commits in the stack may carry the
    trailer while the matching remote branch still points at the
    pre-trailer commit.
    """
    lines = message.rstrip("\n").splitlines()
    while lines and _PR_TRAILER_LINE_RE.match(lines[-1]):
        lines.pop()
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def _parse_pr_trailer(message: str) -> Optional[int]:
    """Parse the `PR: #N` trailer from a commit message.

    Uses `git interpret-trailers --parse` so that we only consider the
    trailer block at the very end of the message — a stray `PR:` line in
    the body must not be picked up.
    """
    if not message.strip():
        return None
    result = subprocess.run(
        ["git", "interpret-trailers", "--parse"],
        input=message,
        capture_output=True,
        text=True,
        check=True,
    )
    pr_number: Optional[int] = None
    for line in result.stdout.splitlines():
        key, sep, value = line.partition(":")
        if not sep or key.strip() != PR_TRAILER_KEY:
            continue
        m = _PR_TRAILER_VALUE_RE.match(value.strip())
        if m:
            pr_number = int(m.group(1))
    return pr_number


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
    if not issue_url and not pr_status and not pr_url and not workflow_statuses:
        return ""

    notes_str = "[ghchain]\n"
    if issue_url:
        notes_str += f"issue = {issue_url}\n"
    if pr_url:
        notes_str += f"pr url = {pr_url}\n"
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


def get_workflow_status(commit_id: str):
    """
    Get the configured workflows status for a given commit id.
    """
    workflow_statuses = []
    for workflow in ghchain.config.workflows:
        workflow_status = WorkflowStatus.from_commit_id(workflow, commit_id=commit_id)
        if workflow_status:
            workflow_statuses.append(workflow_status)
    return workflow_statuses


class Commit(BaseModel):
    """
    Commit object with sha, message, branch, pr_url, notes, and pr_status.
    It is expected that every non-fixup commit has its corresponding branch.
    """

    sha: str
    message: str
    branch: str | None = None
    remote_branches: list[str] = Field(default_factory=list)
    # if the commit is linked to an issue:
    issue_url: str | None = None
    pull_request: PR | None = None
    notes: Optional[str] = None
    workflow_statuses: Optional[list[WorkflowStatus]] = None

    class Config:
        arbitrary_types_allowed = True

    def __init__(
        self,
        with_workflow_status: bool,
        sha: str,
        branch: str | None,
        remote_branches: list[str],
        message: str,
        pull_request: PR | None,
    ):
        super().__init__(
            sha=sha,
            message=message,
            branch=branch,
            pull_request=pull_request,
            remote_branches=remote_branches,
        )

        # extract the linked issue id from the commit message
        self.issue_url = self.extract_issue_url()

        self.workflow_statuses = (
            None if not with_workflow_status else get_workflow_status(sha)
        )

        # Fetch and parse commit notes
        self.notes = get_commit_notes(
            pr_url=self.pull_request.pr_url if self.pull_request else None,
            pr_status=self.pull_request.pr_status if self.pull_request else None,
            issue_url=self.issue_url,
            workflow_statuses=self.workflow_statuses,
        )

        self.update_notes()

    def extract_issue_id(self) -> Optional[int]:
        """Extract the linked-issue ID from the commit title, if any.

        Only the first line is searched — the commit body is excluded so
        that issue references inside body text are not mistaken for the
        commit's linked ticket. If the title's match is actually our own
        trailing `(#PR_ID)` PR reference (matches ``self.pull_request``),
        it is skipped and the next match (if any) is returned.
        """
        title = self.message.split("\n", 1)[0]
        pattern = re.compile(ghchain.config.issue_pattern)
        own_pr_id = self.pull_request.pr_id if self.pull_request else None
        title_pr_ref_match = _TITLE_PR_REF_RE.search(title)
        title_pr_ref = (
            int(title_pr_ref_match.group(1)) if title_pr_ref_match else None
        )
        is_own_pr_ref = (
            own_pr_id is not None and title_pr_ref == own_pr_id
        )
        for match in pattern.finditer(title):
            if (
                is_own_pr_ref
                and int(match.group(1)) == own_pr_id
                and match.end() == len(title.rstrip())
            ):
                continue
            return int(match.group(1))
        return None

    def extract_issue_url(self) -> Optional[str]:
        """
        Extract the issue URL from the commit message.
        """
        issue_id = self.extract_issue_id()
        if issue_id:
            return get_issue_url(issue_id)
        return None

    def update_notes(self):
        # Write the updated notes back to the git notes

        if self.notes:
            ghchain.repo.git.notes("add", "-f", "-m", self.notes, self.sha)

    @property
    def is_fixup(self) -> bool:
        return self.message.startswith("fixup!") or self.message.startswith("squash!")

    @property
    def title(self) -> str:
        """The first line of the commit message."""
        return self.message.split("\n", 1)[0]

    @property
    def pr_trailer(self) -> Optional[int]:
        """The PR number from the commit's `PR: #N` trailer, or None."""
        return _parse_pr_trailer(self.message)

    @property
    def title_pr_ref(self) -> Optional[int]:
        """The PR number from a trailing ` (#N)` ref in the title, or None."""
        match = _TITLE_PR_REF_RE.search(self.title)
        return int(match.group(1)) if match else None

    def has_pr_trailer(self) -> bool:
        return self.pr_trailer is not None

    def add_pr_trailer(self, pr_number: int) -> str:
        """Amend HEAD to carry a `PR: #pr_number` trailer.

        Precondition: this commit's per-PR branch is currently checked
        out (HEAD points at ``self.sha``). Returns the SHA of the
        amended commit. If the commit already carries the requested
        trailer this is a no-op and the existing SHA is returned.
        """
        if self.pr_trailer == pr_number:
            return self.sha

        current_message = ghchain.repo.git.log("-1", "--format=%B", "HEAD")
        rewritten = subprocess.run(
            [
                "git",
                "interpret-trailers",
                "--if-exists",
                "replace",
                "--trailer",
                f"{PR_TRAILER_KEY}: #{pr_number}",
            ],
            input=current_message,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        ghchain.repo.git.commit("--amend", "--no-edit", "-m", rewritten)

        new_sha = ghchain.repo.head.commit.hexsha
        self.sha = new_sha
        self.message = rewritten.strip()
        return new_sha

    def add_pr_to_title(self, pr_number: int) -> str:
        """Amend HEAD to include a trailing ` (#pr_number)` ref in the title.

        If the title already ends with ` (#pr_number)` and the commit
        carries no stale ``PR:`` trailer this is a no-op. If it ends
        with ` (#other)` (e.g. a stale prediction from a prediction
        race), the ref is replaced. Otherwise ` (#pr_number)` is
        appended to the first line. Any existing ``PR: #N`` trailer is
        stripped — title-mode and trailer-mode are mutually exclusive,
        so a leftover trailer (e.g. on a commit cherry-picked from a
        foreign repo) would be misleading.
        """
        if self.title_pr_ref == pr_number and not self.has_pr_trailer():
            return self.sha

        current_message = ghchain.repo.git.log("-1", "--format=%B", "HEAD")
        # Strip any existing PR: trailer left over from trailer-mode.
        stripped = strip_pr_trailer(current_message)
        # Split into title + rest while preserving the exact body bytes.
        title, sep, rest = stripped.partition("\n")
        title = title.rstrip()
        title = _TITLE_PR_REF_RE.sub("", title)
        new_title = f"{title} (#{pr_number})"
        rewritten = new_title + (sep + rest if sep else "")
        # `git commit -m` discards a single trailing newline; preserve
        # the body structure by keeping at least one.
        ghchain.repo.git.commit("--amend", "--no-edit", "-m", rewritten)

        new_sha = ghchain.repo.head.commit.hexsha
        self.sha = new_sha
        self.message = rewritten.strip()
        return new_sha

    def update_pr_ref(self, pr_number: int, mode: str) -> str:
        """Apply the PR reference in the chosen mode and return the new SHA.

        ``mode`` is ``"trailer"`` (dispatches to :meth:`add_pr_trailer`)
        or ``"title"`` (dispatches to :meth:`add_pr_to_title`).
        """
        if mode == "trailer":
            return self.add_pr_trailer(pr_number)
        if mode == "title":
            return self.add_pr_to_title(pr_number)
        raise ValueError(f"unknown PR-ref mode: {mode!r}")
