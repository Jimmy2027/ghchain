import json
from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import Any, Dict, Optional

import ghchain
from ghchain.github_utils import get_pr_id_for_branch
from ghchain.utils import run_command


@dataclass
class WorkflowStatus:
    status: str
    conclusion: str
    name: str
    branch: str
    commit: str
    event: str
    id: str
    elapsed: str
    timestamp: str
    workflow_yml_fn: str

    @classmethod
    def from_line(cls, line: str, workflow_yml_fn: str):
        status, conclusion, name, branch, commit, event, id, elapsed, timestamp = (
            line.split("\t")
        )
        return cls(
            status=status,
            conclusion=conclusion,
            name=name,
            branch=branch,
            commit=commit,
            event=event,
            id=id,
            elapsed=elapsed,
            timestamp=timestamp,
            workflow_yml_fn=workflow_yml_fn,
        )

    @classmethod
    def create(cls, workflow_yml_fn: str, branchname: str):
        result = run_command(
            [
                "gh",
                "run",
                "list",
                "--workflow",
                f"{workflow_yml_fn}.yml",
                "-b",
                branchname,
            ],
            check=True,
        )
        lines = result.stdout.splitlines()
        if lines:
            line = result.stdout.splitlines()[0]
            return WorkflowStatus.from_line(line, workflow_yml_fn)
        return None

    @classmethod
    def from_commit_id(cls, workflow_yml_fn: str, commit_id: str):
        result = run_command(
            [
                "gh",
                "run",
                "list",
                "--commit",
                commit_id,
                "--workflow",
                f"{workflow_yml_fn}.yml",
            ],
            check=True,
        )
        lines = result.stdout.splitlines()
        if lines:
            line = result.stdout.splitlines()[0]
            return WorkflowStatus.from_line(line, "")
        return None

    def to_dict(self) -> Dict[str, any]:
        return self.__dict__


class StatusCheckConclusion(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


class StatusCheckStatus(StrEnum):
    COMPLETED = "COMPLETED"


@dataclass
class StatusCheck:
    completedAt: str
    conclusion: StatusCheckConclusion
    detailsUrl: str
    name: str
    startedAt: str
    status: StatusCheckStatus
    workflowName: str


def string_to_ansi_color(string: str, color: str) -> str:
    """
    Wrap a string in ANSI color codes.
    """
    colors = {
        "black": "\033[30m",
        "red": "\033[31m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "blue": "\033[34m",
        "magenta": "\033[35m",
        "cyan": "\033[36m",
        "white": "\033[37m",
    }
    return f"{colors[color]}{string}\033[0m"


class ReviewDecision(StrEnum):
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NONE = ""


review_decision_colors = {
    ReviewDecision.APPROVED: "green",
    ReviewDecision.CHANGES_REQUESTED: "yellow",
    ReviewDecision.REVIEW_REQUIRED: "red",
    ReviewDecision.NONE: "black",
}


def review_decision_to_ansi(review_decision: ReviewDecision) -> str:
    """
    Convert a review decision to an ANSI color escaped string.
    """
    if (
        review_decision not in review_decision_colors
        or review_decision == ReviewDecision.NONE
    ):
        return review_decision.value
    color = review_decision_colors[review_decision]
    return string_to_ansi_color(review_decision.value, color)


class MergeableStatus(str, Enum):
    MERGEABLE = "MERGEABLE"
    CONFLICTING = "CONFLICTING"
    UNKNOWN = "UNKNOWN"


def mergeable_status_to_ansi(mergeable_status: MergeableStatus) -> str:
    """
    Convert a mergeable status to an ANSI color escaped string.
    """
    if mergeable_status == MergeableStatus.MERGEABLE:
        return string_to_ansi_color(mergeable_status.value, "green")
    elif mergeable_status == MergeableStatus.CONFLICTING:
        return string_to_ansi_color(mergeable_status.value, "red")
    return mergeable_status.value


@dataclass
class PrStatus:
    branchname: str
    pr_id: int
    review_decision: ReviewDecision
    is_draft: bool
    is_mergeable: MergeableStatus
    title: str
    status_checks: Optional[dict[str, StatusCheck]] = None

    @classmethod
    def from_gh_cli_dict(cls, gh_cli_dict: dict):
        return cls(
            branchname=gh_cli_dict["headRefName"],
            pr_id=int(gh_cli_dict["number"]),
            review_decision=ReviewDecision(gh_cli_dict["reviewDecision"]),
            is_draft=gh_cli_dict["isDraft"],
            is_mergeable=MergeableStatus(gh_cli_dict["mergeable"]),
            status_checks={
                status["name"]: StatusCheck(
                    **{
                        k: V
                        for k, V in status.items()
                        if k in StatusCheck.__annotations__
                    }
                )
                for status in gh_cli_dict["statusCheckRollup"]
            }
            if gh_cli_dict["statusCheckRollup"]
            else None,
            title=gh_cli_dict["title"],
        )

    @classmethod
    def from_branchname(cls, branchname: str):
        pr_id = get_pr_id_for_branch(branchname)
        if not pr_id:
            return None
        workflow_statuses = []
        for workflow in ghchain.config.workflows:
            workflow_status = WorkflowStatus.create(workflow, branchname)
            if workflow_status:
                workflow_statuses.append(workflow_status)

        # TODO: add statusCheckRollup
        result = run_command(
            [
                "gh",
                "pr",
                "view",
                pr_id,
                "--json",
                "reviewDecision,isDraft,mergeable,statusCheckRollup,title",
            ],
        )
        result_dict = json.loads(result.stdout)

        return cls(
            branchname=branchname,
            pr_id=int(pr_id),
            review_decision=ReviewDecision(result_dict["reviewDecision"]),
            is_draft=result_dict["isDraft"],
            is_mergeable=MergeableStatus(result_dict["mergeable"]),
            status_checks={
                status["name"]: StatusCheck(
                    **{
                        k: V
                        for k, V in status.items()
                        if k in StatusCheck.__annotations__
                    }
                )
                for status in result_dict["statusCheckRollup"]
            }
            if result_dict["statusCheckRollup"]
            else None,
            title=result_dict["title"],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "branchname": self.branchname,
            "pr_id": self.pr_id,
            "review_decision": self.review_decision.value,
            "is_draft": self.is_draft,
            "is_mergeable": self.is_mergeable.value,
            "title": self.title,
        }
