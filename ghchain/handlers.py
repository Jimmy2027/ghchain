import json

import click

import ghchain
from ghchain.utils import run_command


def handle_land(branch):
    """
    Merge the specified branch into the configured base branch.
    This will close the corresponding PRs and delete the branch if configured to do so.
    """

    if (
        branch not in ghchain.repo.branches
        or ghchain.repo.branches[branch].commit
        != ghchain.repo.remotes.origin.refs[branch].commit
    ):
        # if the branch is not up to date, pull the latest changes
        if click.confirm(
            f"The local branch '{branch}' is out of date with the remote. Do you want to update it?"
        ):
            try:
                run_command(
                    ["git", "fetch", "origin", f"{branch}:{branch}"], check=True
                )
            except Exception as e:
                ghchain.logger.error(
                    f"Failed to pull the latest changes from the remote: {e}"
                )
                return
        else:
            ghchain.logger.error(
                f"Branch '{branch}' is not up to date with the remote. Aborting."
            )
            return

    # update the base branch
    run_command(
        [
            "git",
            "branch",
            "-f",
            ghchain.config.base_branch.replace("origin/", ""),
            branch,
        ],
        check=True,
    )
    run_command(
        ["git", "push", "origin", ghchain.config.base_branch.replace("origin/", "")],
        check=True,
    )

    if ghchain.config.delete_branch_after_merge:
        # List all open PRs targeting the branch to be deleted
        prs = json.loads(
            run_command(
                [
                    "gh",
                    "pr",
                    "list",
                    "--json",
                    "number",
                    "--state",
                    "open",
                    "--base",
                    branch,
                ],
                check=True,
            ).stdout
        )

        # Change the base branch of all those PRs to target the configured base branch
        for pr in prs:
            run_command(
                [
                    "gh",
                    "pr",
                    "edit",
                    str(pr["number"]),
                    "--base",
                    ghchain.config.base_branch.replace("origin/", ""),
                ],
                # Don't check here because somethimes github updates the PRs faster than the CLI
                check=False,
            )

        # Delete the remote branch, don't check since the branch might already be deleted
        run_command(["git", "push", "origin", "--delete", branch], check=False)
        # Delete the local branch
        run_command(["git", "branch", "-D", branch], check=True)
