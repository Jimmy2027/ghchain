from typing import List, Optional

import click
from loguru import logger
from pydantic import BaseModel

import ghchain
from ghchain.commit import Commit
from ghchain.git_utils import (
    create_branch_name,
    get_all_branches,
    get_current_branch,
    git_push,
)
from ghchain.github_utils import (
    create_branch_from_issue,
    get_next_gh_id,
)
from ghchain.pull_request import (
    PR,
    get_open_prs,
    run_tests_on_branch,
    update_pr_descriptions,
)
from ghchain.utils import run_command


class Stack(BaseModel):
    commits: List[Commit]
    dev_branch: str
    base_branch: str

    @classmethod
    def create(
        cls, base_branch: Optional[str] = None, with_workflow_status: bool = False
    ) -> "Stack":
        """
        Create a Stack object with commits from the current branch which are not in the base branch.

        Args:
            base_branch: The base branch to compare the commits against. Defaults to the base branch in the config.
            dev_branch: The development branch to create the stack from. Defaults to the current branch.

        """

        sha_to_pull_request_mapping: dict[str, PR] = {
            pr.commits[-1]: pr for pr in get_open_prs()
        }

        if not base_branch:
            base_branch = ghchain.config.base_branch
        dev_branch = get_current_branch()

        logger.debug(f"Creating stack with dev branch: {dev_branch}")

        # Fetch the commits that are in dev_branch but not in base_branch
        commits_diff = ghchain.repo.iter_commits(f"{base_branch}..{dev_branch}")

        commits = []
        # Reverse log output to start from the bottom of the stack
        for commit in reversed(list(commits_diff)):
            sha = commit.hexsha
            message = str(commit.message.strip())
            is_fixup = message.startswith("fixup!")

            # Find branches that point to this commit (branches where this commit is the HEAD)
            pointing_branches = [
                ref.name.split("/")[-1]
                for ref in ghchain.repo.branches
                if ref.commit == commit
            ]
            pointing_branches = set(pointing_branches) - {
                dev_branch
            }  # Exclude the dev branch

            if len(pointing_branches) > 1:
                error_message = f"Commit {sha} has multiple branches: {pointing_branches}. This is not supported."
                logger.error(error_message)
                raise ValueError(error_message)

            branch = pointing_branches.pop() if pointing_branches else None
            commit_obj = Commit(
                with_workflow_status=with_workflow_status,
                sha=sha,
                branch=branch,
                message=message,
                pull_request=sha_to_pull_request_mapping.get(sha),
            )
            commits.append(commit_obj)

            if is_fixup:
                # Find the previous commit that is not a fixup and assign it the same branch
                target_commit = next(
                    (
                        commit
                        for commit in commits[::-1]
                        if not commit.is_fixup and not commit.branch
                    ),
                    None,
                )
                if target_commit:
                    target_commit.branch = commit_obj.branch

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
            if commit.issue_url:
                logger.info(f"Creating branch from issue {commit.issue_url}")
                # set a temporary branch name as it will be created later
                branch_name = "{will be created from issue}"

            else:
                branch_id = max([get_next_gh_id(), *[id + 1 for id in self.branch_ids]])
                branch_name = create_branch_name(
                    ghchain.config.branch_name_template, branch_id
                )
            click.confirm(
                f"Create branch {branch_name} for commit {commit.sha}?\n{commit.message}\n",
                abort=True,
                default=True,
            )
            logger.info(f"Creating branch {branch_name} for commit {commit.sha}")
            if commit.issue_url:
                # create the branch from the gh issue
                branch_name = create_branch_from_issue(
                    issue_id=int(commit.issue_url.split("/")[-1]),
                    base_commit=commit.sha,
                )
            else:
                ghchain.repo.git.branch(branch_name, commit.sha)
            commit.branch = branch_name

            # Push the branch to the remote
            git_push(branch_name)

        else:
            branch_name = commit.branch

        # If the commit is not a fixup and it does not have a PR, create one
        if not commit.is_fixup and create_pr and not commit.pull_request:
            commit.pull_request = PR.create_pull_request(
                base_branch=ghchain.config.base_branch.replace("origin/", "")
                if not self.commit2idx[commit.sha]
                else self.commits[self.commit2idx[commit.sha] - 1].branch,
                head_branch=branch_name,
                title=commit.message.split("\n")[0],
                body=commit.message,
                draft=draft,
                commit_sha=commit.sha,
            )
            pr_created = True

        if create_pr:
            update_pr_descriptions(
                pr_stack=[
                    c.pull_request
                    for c in self.commits[: self.commit2idx[commit.sha] + 1]
                    if c.pull_request
                ]
            )

        if with_tests:
            run_tests_on_branch(branch_name, commit.pull_request)

        return pr_created

    def publish(self):
        """
        Collect all branches in the stack that need to be pushed to the remote,
        ask the user for confirmation, and then push them all with force-with-lease.
        """
        branches_to_push = []

        # Collect branches that need to be pushed
        for commit in self.commits:
            if not commit.branch:
                logger.trace(
                    f"Commit {commit.sha} does not have an associated branch. Skipping."
                )
                continue

            branch_name = commit.branch
            remote_branch = f"origin/{branch_name}"

            try:
                local_sha = ghchain.repo.git.rev_parse(branch_name)
                remote_sha = ghchain.repo.git.rev_parse(remote_branch)

                if local_sha != remote_sha:
                    branches_to_push.append(branch_name)
            except Exception:
                # Remote branch does not exist
                branches_to_push.append(branch_name)

        if not branches_to_push:
            logger.info("All branches are up-to-date with the remote. Nothing to push.")
            return

        # Confirm with the user
        click.confirm(
            f"The following branches will be pushed with --force-with-lease:\n{', '.join(branches_to_push)}\n"
            "Do you want to proceed?",
            abort=True,
        )

        # Push all branches with --force-with-lease
        try:
            ghchain.repo.git.push("--force-with-lease", "origin", *branches_to_push)
            logger.info(
                f"Successfully pushed branches: {', '.join(branches_to_push)} with --force-with-lease."
            )
        except Exception as push_error:
            logger.error(
                f"Failed to push branches: {', '.join(branches_to_push)}: {push_error}"
            )

        logger.info("Publishing complete.")


def find_branch_of_rebased_commit(commit: Commit) -> str:
    """
    When a commit is rebased, the commit hash changes. This function checks if there is any branch
    that has a commit with the message as top commit. If there is, it returns the branch name.
    """
    # Get the commit message
    commit_message = commit.message

    # List all branches
    result = get_all_branches()
    branches = result.stdout.splitlines()

    # Check the top commit message of each branch
    for branch in branches:
        branch = branch.strip().replace(
            "* ", ""
        )  # Remove leading '*' for the current branch
        result = run_command(
            ["git", "log", "-1", "--pretty=%B", branch],
            check=True,
        )
        top_commit_message = result.stdout.strip()
        if top_commit_message == commit_message:
            logger.debug(f"Found branch {branch} with commit message {commit_message}")
            return branch

    return None
