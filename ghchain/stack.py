from collections import defaultdict
from typing import List, Optional

import click
from git import Head, RemoteReference
from loguru import logger
from pydantic import BaseModel

import ghchain
from ghchain.commit import Commit
from ghchain.git_utils import (
    create_branch_name,
    get_all_branches,
    get_branches_in_other_worktrees,
    get_current_branch,
    git_push,
)
from ghchain.github_utils import (
    create_branch_from_issue,
    get_next_gh_id,
    get_pr_head_branch,
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
        # Match open PRs to local commits two ways:
        #  - by SHA: the common case, when local has not diverged from
        #    what was last pushed for the PR;
        #  - by head branch: the fallback when the local commit has been
        #    amended (e.g. by ghchain itself in an earlier run, or by
        #    rebase) and no longer matches the PR's tip SHA on the
        #    remote. Without this fallback, ghchain would try to
        #    recreate the PR and `gh pr create` would refuse with
        #    "already exists", surfacing as a confusing NoneType crash
        #    when Step 8 reads ``commit.pull_request.pr_id``.
        open_prs = get_open_prs()
        sha_to_pull_request_mapping: dict[str, PR] = {
            pr.commits[-1]: pr for pr in open_prs
        }
        branch_to_pull_request_mapping: dict[str, PR] = {
            pr.head_branch: pr for pr in open_prs
        }

        base_branch = base_branch or ghchain.config.base_branch
        dev_branch = get_current_branch()

        logger.debug(f"Creating stack with dev branch: {dev_branch}")

        # Create mappings for commit SHA to local and remote branch names
        commit_to_local_refs = defaultdict(list)
        commit_to_remote_refs = defaultdict(list)
        for ref in ghchain.repo.references:
            if not ref.commit:
                continue
            commit_sha = ref.commit.hexsha
            if isinstance(ref, RemoteReference):
                commit_to_remote_refs[commit_sha].append(ref.name)
            elif isinstance(ref, Head):
                commit_to_local_refs[commit_sha].append(ref.name)

        # Fetch commits in dev_branch but not in base_branch
        commits_diff = list(ghchain.repo.iter_commits(f"{base_branch}..{dev_branch}"))
        commits = []

        # Process commits in reverse order (bottom of the stack first)
        for commit in reversed(commits_diff):
            sha = commit.hexsha
            message = commit.message.strip()
            is_fixup = message.startswith("fixup!")

            # Exclude the dev branch from local branch candidates
            pointing_branches = set(commit_to_local_refs[sha]) - {dev_branch}
            if len(pointing_branches) > 1:
                error_message = f"Commit {sha} has multiple branches: {pointing_branches}. This is not supported."
                logger.error(error_message)
                raise ValueError(error_message)
            branch = pointing_branches.pop() if pointing_branches else None

            pull_request = sha_to_pull_request_mapping.get(sha)
            if pull_request is None and branch is not None:
                pull_request = branch_to_pull_request_mapping.get(branch)
            commit_obj = Commit(
                with_workflow_status=with_workflow_status,
                sha=sha,
                branch=branch,
                remote_branches=commit_to_remote_refs[sha],
                message=message,
                pull_request=pull_request,
            )
            commits.append(commit_obj)

            if is_fixup:
                # Assign branch to the most recent non-fixup commit without a branch
                for previous_commit in reversed(commits[:-1]):
                    if not previous_commit.is_fixup and not previous_commit.branch:
                        previous_commit.branch = commit_obj.branch
                        break

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

    def _get_branch_target_sha(self, commit: Commit) -> str:
        """
        For a non-fixup commit, return the SHA of the last consecutive fixup commit
        that follows it in the stack. If there are no fixups, return the commit's own SHA.
        This ensures the branch includes the commit and all its fixup commits.
        """
        idx = self.commit2idx[commit.sha]
        target_sha = commit.sha
        for following in self.commits[idx + 1 :]:
            if following.is_fixup:
                target_sha = following.sha
            else:
                break
        return target_sha

    def process_stack(
        self,
        create_pr: bool = False,
        draft: bool = False,
        with_tests: bool = False,
    ):
        """Walk the stack bottom-up, processing each commit.

        When ``create_pr`` is True this performs:
         predict-PR → amend-with-trailer
        → push → create-PR → verify-and-repair → rebase --update-refs
        to advance downstream refs. After each iteration the in-memory
        stack is refreshed from git so subsequent commits see their
        post-rebase SHAs.
        """
        if create_pr:
            self._check_no_branches_in_other_worktrees()

        for i in range(len(self.commits)):
            commit = self.commits[i]
            self.process_commit(
                commit, create_pr=create_pr, draft=draft, with_tests=with_tests
            )
            if create_pr:
                self._refresh_from_git()

    def _check_no_branches_in_other_worktrees(self):
        """Abort if any per-commit branch is checked out in another worktree.

        `git rebase --update-refs` cannot move a ref that another worktree
        has locked, so this would manifest as a confusing mid-cascade
        failure. Surfacing it up front keeps the stack pristine.
        """
        in_other = get_branches_in_other_worktrees()
        stack_branches = {c.branch for c in self.commits if c.branch}
        conflict = stack_branches & in_other
        if conflict:
            raise click.ClickException(
                f"Cannot run `ghchain -p`: branch(es) {sorted(conflict)} are "
                "checked out in another worktree, which prevents "
                "`git rebase --update-refs`. Close those worktrees (or check "
                "out a different branch there) and re-run."
            )

    def _refresh_from_git(self):
        """Update SHAs and messages of self.commits after a cascade rebase.

        The cascade preserves commit count; we map old → new by stack
        position. Other Commit-object fields (branch, pull_request,
        issue_url, notes) are preserved.
        """
        new_commits = list(
            ghchain.repo.iter_commits(f"{self.base_branch}..{self.dev_branch}")
        )
        new_commits.reverse()
        if len(new_commits) != len(self.commits):
            logger.warning(
                f"Stack size changed during processing "
                f"({len(self.commits)} → {len(new_commits)}); skipping refresh."
            )
            return
        for ours, theirs in zip(self.commits, new_commits):
            ours.sha = theirs.hexsha
            ours.message = theirs.message.strip()

    def _cascade_rebase(self, old_sha: str, new_sha: str):
        """Advance dev_branch and downstream per-commit branches onto new_sha."""
        if old_sha == new_sha:
            return
        run_command(
            [
                "git",
                "rebase",
                "--update-refs",
                "--onto",
                new_sha,
                old_sha,
                self.dev_branch,
            ],
            check=True,
        )

    def _rename_branch(self, old_name: str, new_name: str):
        """Rename a local branch and delete the stale remote branch (best-effort)."""
        ghchain.repo.git.branch("-m", old_name, new_name)
        try:
            ghchain.repo.git.push(ghchain.config.remote, "--delete", old_name)
        except Exception as e:
            logger.warning(f"Failed to delete stale remote branch {old_name}: {e}")

    def process_commit(
        self,
        commit: Commit,
        create_pr: bool = False,
        draft: bool = False,
        with_tests: bool = False,
    ):
        """Process a single commit.

        Without ``create_pr``: just ensure a per-commit branch exists.
        With ``create_pr``: run the pre-amend trailer flow for this
        commit (predict → amend → push → create-PR → verify-and-repair).
        Fixup commits are skipped — they ride along on their parent's branch.
        """
        pr_created = False

        if commit.is_fixup:
            logger.debug(f"Skipping fixup commit {commit.sha}: {commit.message}")
            return pr_created

        branch_target_sha = self._get_branch_target_sha(commit)

        if not create_pr:
            if not commit.branch:
                commit.branch = self._create_branch_for_commit(
                    commit, branch_target_sha
                )
                git_push(commit.branch)
            if with_tests:
                run_tests_on_branch(commit.branch, commit.pull_request)
            return pr_created

        return self._process_commit_with_pr(
            commit, branch_target_sha, draft, with_tests
        )

    def _create_branch_for_commit(self, commit: Commit, branch_target_sha: str) -> str:
        """Interactively create a per-commit branch and return its name."""
        if commit.issue_url:
            logger.info(f"Creating branch from issue {commit.issue_url}")
            display_name = "{will be created from issue}"
        else:
            branch_id = max([get_next_gh_id(), *[id + 1 for id in self.branch_ids]])
            display_name = create_branch_name(
                ghchain.config.branch_name_template, branch_id
            )

        click.confirm(
            f"Create branch {display_name} for commit {commit.sha}?\n{commit.message}\n",
            abort=True,
            default=True,
        )
        logger.info(f"Creating branch {display_name} for commit {commit.sha}")

        if commit.issue_url:
            return create_branch_from_issue(
                issue_id=int(commit.issue_url.split("/")[-1]),
                base_commit=branch_target_sha,
            )
        ghchain.repo.git.branch(display_name, branch_target_sha)
        return display_name

    def _decide_pr_ref_mode(
        self, commit: Commit, branch_name: str, target_pr_id: int
    ) -> tuple[str, bool]:
        """Pick PR-ref placement mode and detect idempotent no-ops.

        Returns ``(mode, skip_amend)`` where ``mode`` is ``"trailer"``
        or ``"title"``.

        The decision proceeds in three layers:

        1. **Trust an existing marker.** A ``PR: #N`` trailer or a
           trailing ``(#N)`` in the title is trusted iff ``N`` is real
           — either ``commit.pull_request`` (locally cached open PR)
           names it, or a ``gh pr view`` lookup shows PR ``#N`` whose
           head points at ``branch_name``. The first trustworthy marker
           wins.
        2. **In-progress amend.** If the title already ends with
           ``(#target_pr_id)`` (e.g. amended earlier in this same run,
           PR not yet created), treat as title-mode idempotent.
        3. **Fresh decision.** If the title links a ticket
           (``commit.extract_issue_id()`` finds a non-self ``(#N)``),
           use trailer-mode. Otherwise, title-mode.
        """
        # Case 1: trust an existing trailer.
        if commit.has_pr_trailer() and self._marker_points_at_branch(
            commit, branch_name, commit.pr_trailer
        ):
            return ("trailer", True)

        # Case 2: trust an existing title PR ref.
        if commit.title_pr_ref is not None and self._marker_points_at_branch(
            commit, branch_name, commit.title_pr_ref
        ):
            return ("title", True)

        # Case 3: title already ends with our predicted ref (PR not yet
        # opened, but we amended earlier in this same run).
        if commit.title_pr_ref == target_pr_id:
            return ("title", True)

        # Cases 4 and 5: distinguish ticket-in-title from no-ticket.
        # ``extract_issue_id`` (title-only, skips our own PR ref) is the
        # canonical "is there a ticket linked" check.
        ticket_id = commit.extract_issue_id()
        if ticket_id is not None and ticket_id != target_pr_id:
            return ("trailer", False)
        return ("title", False)

    def _marker_points_at_branch(
        self, commit: Commit, branch_name: str, ref_id: int
    ) -> bool:
        """True if PR ``#ref_id`` actually exists for ``branch_name``.

        Trusts locally-cached open PR info first; falls back to a
        ``gh pr view`` lookup when no PR is cached for this commit.
        """
        if commit.pull_request and ref_id == commit.pull_request.pr_id:
            return True
        if not commit.pull_request:
            return get_pr_head_branch(ref_id) == branch_name
        return False

    def _process_commit_with_pr(
        self,
        commit: Commit,
        branch_target_sha: str,
        draft: bool,
        with_tests: bool,
    ) -> bool:
        pr_created = False

        # Step 1: resolve the target PR id — use the existing PR if we
        # already opened one for this commit, otherwise predict.
        if commit.pull_request:
            target_pr_id = commit.pull_request.pr_id
        else:
            target_pr_id = max(
                [get_next_gh_id(), *[id + 1 for id in self.branch_ids]]
            )

        # Step 2: ensure the per-commit branch exists.
        if not commit.branch:
            if commit.issue_url:
                click.confirm(
                    f"Create branch from issue {commit.issue_url} "
                    f"for commit {commit.sha}?\n{commit.message}\n",
                    abort=True,
                    default=True,
                )
                branch_name = create_branch_from_issue(
                    issue_id=int(commit.issue_url.split("/")[-1]),
                    base_commit=branch_target_sha,
                )
            else:
                branch_name = create_branch_name(
                    ghchain.config.branch_name_template, target_pr_id
                )
                click.confirm(
                    f"Create branch {branch_name} for commit {commit.sha}?\n{commit.message}\n",
                    abort=True,
                    default=True,
                )
                ghchain.repo.git.branch(branch_name, branch_target_sha)
            commit.branch = branch_name
        else:
            branch_name = commit.branch

        # Step 3: decide PR-ref placement mode + idempotency.
        # The mode is determined by whether the title already links a
        # ticket. A trailing ` (#N)` matching ``target_pr_id`` is treated
        # as our own previously-added PR ref (title-mode idempotency);
        # any other ``(#N)`` in the title is treated as a ticket and
        # selects trailer-mode.
        mode, skip_amend = self._decide_pr_ref_mode(
            commit, branch_name, target_pr_id
        )
        # The trust check for an existing trailer may discover that the
        # commit already names a real PR — adopt that PR id as target.
        if skip_amend and mode == "trailer" and commit.has_pr_trailer():
            target_pr_id = commit.pr_trailer
        elif skip_amend and mode == "title":
            target_pr_id = commit.title_pr_ref

        # Step 4: amend the *logical* (non-fixup) commit with the chosen
        # PR ref. We detach-checkout commit.sha so the amend lands on the
        # non-fixup parent even when the branch tip is a fixup commit
        # above it.
        old_sha = commit.sha
        if skip_amend:
            new_sha = old_sha
            amended = False
        else:
            branch_was_at_old_sha = (
                ghchain.repo.git.rev_parse(branch_name) == old_sha
            )
            ghchain.repo.git.checkout(old_sha)
            new_sha = commit.update_pr_ref(target_pr_id, mode)
            amended = new_sha != old_sha
            if amended and branch_was_at_old_sha:
                # No fixups on top → the branch needs a manual fast-forward
                # (the cascade rebase below has an empty fixup range here).
                ghchain.repo.git.branch("-f", branch_name, new_sha)

        # Step 5: cascade-rebase old_sha..dev_branch onto new_sha. This
        # advances the per-commit branch (via --update-refs for fixup tails),
        # downstream per-commit branches, and dev_branch in one step.
        if amended:
            self._cascade_rebase(old_sha, new_sha)

        # Step 6: push the per-commit branch (force-with-lease if amended
        # over a stale remote tip).
        try:
            ghchain.repo.git.push(ghchain.config.remote, branch_name)
        except Exception:
            ghchain.repo.git.push(
                "--force-with-lease", ghchain.config.remote, branch_name
            )

        # Step 7: create the PR if we haven't yet.
        if not commit.pull_request:
            commit_idx = self.commit2idx[commit.sha]
            base_branch_for_pr = (
                ghchain.config.base_branch.replace("origin/", "")
                if commit_idx == 0
                else self.commits[commit_idx - 1].branch
            )
            commit.pull_request = PR.create_pull_request(
                base_branch=base_branch_for_pr,
                head_branch=branch_name,
                title=commit.message.split("\n")[0],
                body=commit.message,
                draft=draft,
                commit_sha=commit.sha,
                linked_issue=int(commit.issue_url.split("/")[-1])
                if commit.issue_url
                else None,
            )
            if commit.pull_request is None:
                raise click.ClickException(
                    f"Failed to create pull request for branch {branch_name!r}. "
                    "See the `gh` error above. If a PR for this branch already "
                    "exists on GitHub, make sure it's open and re-run."
                )
            pr_created = True

            # Step 8: verify and repair if GitHub assigned a different number.
            actual_pr_id = commit.pull_request.pr_id
            if actual_pr_id != target_pr_id:
                logger.warning(
                    f"PR-prediction race: predicted #{target_pr_id} but GitHub "
                    f"assigned #{actual_pr_id}. Repairing PR ref ({mode}-mode) "
                    "and renaming branch."
                )
                repair_old_sha = commit.sha
                branch_was_at_repair_sha = (
                    ghchain.repo.git.rev_parse(branch_name) == repair_old_sha
                )
                ghchain.repo.git.checkout(repair_old_sha)
                repair_new_sha = commit.update_pr_ref(actual_pr_id, mode)
                if branch_was_at_repair_sha:
                    ghchain.repo.git.branch("-f", branch_name, repair_new_sha)
                self._cascade_rebase(repair_old_sha, repair_new_sha)

                if not commit.issue_url:
                    new_branch_name = create_branch_name(
                        ghchain.config.branch_name_template, actual_pr_id
                    )
                    if new_branch_name != branch_name:
                        self._rename_branch(branch_name, new_branch_name)
                        commit.branch = new_branch_name
                        branch_name = new_branch_name
                ghchain.repo.git.push(
                    "--force-with-lease", ghchain.config.remote, branch_name
                )

        # Step 10: update PR descriptions for the stack so far.
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
        branches_to_push: list[str] = []
        seen_branches: set[str] = set()

        # Collect branches that need to be pushed
        for commit in self.commits:
            if not commit.branch:
                logger.trace(
                    f"Commit {commit.sha} does not have an associated branch. Skipping."
                )
                continue

            branch_name = commit.branch
            if branch_name in seen_branches:
                continue
            seen_branches.add(branch_name)
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
            ghchain.repo.git.push(
                "--force-with-lease", ghchain.config.remote, *branches_to_push
            )
            logger.info(
                f"Successfully pushed branches: {', '.join(branches_to_push)} with --force-with-lease."
            )
        except Exception as push_error:
            logger.error(
                f"Failed to push branches: {', '.join(branches_to_push)}: {push_error}"
            )

        logger.info("Publishing complete.")

    def download(self):
        """
        Pull rebase every local branch in the stack with origin.
        """
        for commit in self.commits:
            if not commit.remote_branches:
                logger.trace(
                    f"Commit {commit.sha} does not have an associated branch. Skipping."
                )
                continue

            if not len(commit.remote_branches) == 1:
                logger.error(
                    f"Commit {commit.sha} has multiple remote branches: {commit.remote_branches}."
                )
                raise ValueError(
                    f"Commit {commit.sha} has multiple remote branches: {commit.remote_branches}."
                )
            branch_name = commit.remote_branches[0].removeprefix(
                f"{ghchain.config.remote}/"
            )
            try:
                ghchain.repo.git.checkout(branch_name)
                ghchain.repo.git.pull("--rebase", ghchain.config.remote, branch_name)
            except Exception as e:
                logger.error(f"Failed to pull rebase branch {branch_name}: {e}")

        logger.info("Download complete.")

    @classmethod
    def generate_branch_name(cls, commit: Commit) -> str:
        """
        Generate a branch name for the given commit based on the configured template.
        """
        branch_id = max([get_next_gh_id(), *[id + 1 for id in cls.branch_ids]])
        return create_branch_name(ghchain.config.branch_name_template, branch_id)

    @classmethod
    def find_branch_of_rebased_commit(cls, commit: Commit) -> str:
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
                logger.debug(
                    f"Found branch {branch} with commit message {commit_message}"
                )
                return branch

        return None

    def pull_rebase(self):
        """
        Pull rebase every local branch in the stack with origin.
        """
        current_branch = get_current_branch()
        for commit in self.commits:
            for branch_name in commit.branches:
                if branch_name == self.dev_branch:
                    continue
                logger.info(f"Pull rebase branch: {branch_name}")
                ghchain.repo.git.checkout(branch_name)
                ghchain.repo.git.pull("--rebase", ghchain.config.remote, branch_name)
        ghchain.repo.git.checkout(current_branch)
