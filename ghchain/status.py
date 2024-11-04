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
            # "status_checks": {
            #     k: v.to_dict() for k, v in (self.status_checks or {}).items()
            # },
        }


@dataclass
class StatusRow:
    branch: str
    pr_id: int
    review_decision: Optional[str]
    is_draft: bool
    workflow_status: str
    status_checks: str
    title: str

    @staticmethod
    def status2color(status: str, conclusion: str):
        status = status.lower()
        conclusion = conclusion.lower()

        if conclusion == "success":
            return "bright_green"
        elif status in ["queued", "in_progress"] or conclusion == "neutral":
            return "yellow"
        else:
            return "bright_red"

    @classmethod
    def from_pr_status(cls, pr_status: PrStatus):
        workflow_status_str = ""
        for workflow_status in pr_status.workflow_statuses:
            if workflow_status:
                color = cls.status2color(
                    workflow_status.status, workflow_status.conclusion
                )
                workflow_status_str += (
                    f"[bold {color}]{workflow_status.workflow_yml_fn}[/]:"
                    " {workflow_status.status, workflow_status.conclusion}\n"
                )

        status_check_str = ""
        if pr_status.status_checks:
            for status_check in pr_status.status_checks.values():
                color = cls.status2color(status_check.status, status_check.conclusion)
                status_check_str += (
                    f"[bold {color}]{status_check.name}[/]:"
                    " {status_check.status, status_check.conclusion}\n"
                )

        return cls(
            branch=pr_status.branchname,
            pr_id=pr_status.pr_id,
            review_decision=pr_status.review_decision,
            is_draft=pr_status.is_draft,
            workflow_status=workflow_status_str,
            status_checks=status_check_str,
            title=pr_status.title,
        )

    def to_row(self):
        review_decision_color = (
            "bright_green" if self.review_decision == "APPROVED" else "default"
        )
        return [
            f"[bold gray]{self.branch}[/]\n\t{self.title}",
            str(self.pr_id),
            f"[bold {review_decision_color}]{self.review_decision}[/]",
            str(self.is_draft),
            self.workflow_status,
            self.status_checks,
        ]
