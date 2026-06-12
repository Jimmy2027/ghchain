"""Tests for Commit.add_pr_to_title / title_pr_ref and the title-mode
adaptation of Commit.extract_issue_id (which now searches the title only
and skips our own trailing ``(#PR_ID)`` ref)."""

import os
from pathlib import Path

import pytest
from git import Repo


@pytest.fixture
def git_repo(mocker, tmp_path):
    os.chdir(tmp_path)
    repo = Repo.init(tmp_path)
    repo.git.checkout(b="main")
    Path("README.md").write_text("hello\n")
    repo.index.add(["README.md"])
    repo.index.commit("initial commit")
    mocker.patch("ghchain.repo", repo)
    return repo


@pytest.fixture
def commit_factory(mocker, git_repo):
    """Return a function that materializes a Commit on HEAD with a given
    message and optional pull_request."""
    from ghchain.commit import Commit

    mocker.patch.object(Commit, "update_notes")
    mocker.patch("ghchain.commit.get_workflow_status", return_value=[])
    mocker.patch("ghchain.commit.get_issue_url", side_effect=lambda i: f"http://x/{i}")

    def _make(message: str, pull_request=None):
        head_sha = git_repo.head.commit.hexsha
        return Commit(
            sha=head_sha,
            message=message,
            branch=None,
            remote_branches=[],
            pull_request=pull_request,
            with_workflow_status=False,
        )

    return _make


def _amend_message(repo: Repo, message: str) -> None:
    repo.git.commit("--amend", "--no-edit", "-m", message)


def _make_pr(pr_id: int):
    """Construct a minimal PR pydantic-ish object for tests."""
    from ghchain.pull_request import PR

    return PR(
        pr_id=pr_id,
        pr_url=f"http://x/pull/{pr_id}",
        pr_status=None,
        head_branch=f"hk-{pr_id}",
        body="",
        title="",
        commits=[],
    )


# ---------------------------------------------------------------------------
# title_pr_ref
# ---------------------------------------------------------------------------


def test_title_pr_ref_none_when_absent(commit_factory):
    assert commit_factory("fix bug\n\nbody\n").title_pr_ref is None


def test_title_pr_ref_parses_trailing_ref(commit_factory):
    assert commit_factory("fix bug (#42)\n\nbody\n").title_pr_ref == 42


def test_title_pr_ref_ignores_non_trailing_match(commit_factory):
    """A ``(#N)`` mid-title (e.g. ``Refactor (#42) for foo``) is NOT a
    PR ref — only trailing ones are."""
    assert commit_factory("Refactor (#42) for foo\n").title_pr_ref is None


def test_title_pr_ref_requires_leading_whitespace(commit_factory):
    """``(#42)`` flush against the first word is not a trailing PR ref."""
    assert commit_factory("fix(#42)\n").title_pr_ref is None


# ---------------------------------------------------------------------------
# add_pr_to_title
# ---------------------------------------------------------------------------


def test_add_pr_to_title_fresh_add(git_repo, commit_factory):
    _amend_message(git_repo, "fix bug\n\nbody\n")
    commit = commit_factory("fix bug\n\nbody\n")

    old_sha = commit.sha
    new_sha = commit.add_pr_to_title(7)

    assert new_sha != old_sha
    assert commit.sha == new_sha
    assert commit.title_pr_ref == 7
    head_msg = git_repo.git.log("-1", "--format=%B", "HEAD")
    assert head_msg.splitlines()[0] == "fix bug (#7)"
    # Body preserved.
    assert "body" in head_msg


def test_add_pr_to_title_replaces_trailing_ref(git_repo, commit_factory):
    """A stale ``(#99)`` from a prediction race is replaced."""
    _amend_message(git_repo, "fix bug (#99)\n\nbody\n")
    commit = commit_factory("fix bug (#99)\n\nbody\n")

    commit.add_pr_to_title(7)

    head_msg = git_repo.git.log("-1", "--format=%B", "HEAD")
    assert head_msg.splitlines()[0] == "fix bug (#7)"
    assert "(#99)" not in head_msg


def test_add_pr_to_title_noop_when_matching(git_repo, commit_factory):
    _amend_message(git_repo, "fix bug (#7)\n\nbody\n")
    commit = commit_factory("fix bug (#7)\n\nbody\n")

    sha_before = commit.sha
    returned = commit.add_pr_to_title(7)

    assert returned == sha_before
    assert commit.sha == sha_before


def test_add_pr_to_title_strips_stale_pr_trailer(git_repo, commit_factory):
    """When transitioning to title-mode, any leftover ``PR: #N`` trailer
    is stripped — mixing the two modes would be misleading."""
    msg = "fix bug\n\nbody\n\nPR: #99\n"
    _amend_message(git_repo, msg)
    commit = commit_factory(msg)

    commit.add_pr_to_title(7)

    head_msg = git_repo.git.log("-1", "--format=%B", "HEAD")
    assert head_msg.splitlines()[0] == "fix bug (#7)"
    assert "PR: #99" not in head_msg
    assert "PR: #" not in head_msg


def test_add_pr_to_title_preserves_other_trailers(git_repo, commit_factory):
    """Non-PR trailers (Signed-off-by, etc.) survive the amend."""
    msg = "fix bug\n\nbody\n\nSigned-off-by: Test User <test@example.com>\n"
    _amend_message(git_repo, msg)
    commit = commit_factory(msg)

    commit.add_pr_to_title(11)

    head_msg = git_repo.git.log("-1", "--format=%B", "HEAD")
    assert head_msg.splitlines()[0] == "fix bug (#11)"
    assert "Signed-off-by: Test User <test@example.com>" in head_msg


# ---------------------------------------------------------------------------
# extract_issue_id: title-only + skips own PR ref
# ---------------------------------------------------------------------------


def test_extract_issue_id_finds_ticket_in_title(commit_factory):
    commit = commit_factory("fix login bug (#42)\n\nbody\n")
    assert commit.extract_issue_id() == 42


def test_extract_issue_id_ignores_body(commit_factory):
    """A ``(#N)`` only present in the body is NOT a linked ticket."""
    commit = commit_factory("fix bug\n\nsee discussion in (#42)\n")
    assert commit.extract_issue_id() is None


def test_extract_issue_id_skips_own_pr_ref(commit_factory):
    """A trailing ``(#N)`` matching the commit's own PR id is our PR
    ref, not a ticket."""
    commit = commit_factory(
        "fix bug (#100)\n\nbody\n",
        pull_request=_make_pr(100),
    )
    assert commit.extract_issue_id() is None
    assert commit.issue_url is None


def test_extract_issue_id_keeps_ticket_when_pr_ref_after(commit_factory):
    """``fix bug (#42)`` shouldn't get a trailing ``(#PR)`` (we'd use
    trailer mode instead), but if it ever happened, the *first* match
    is the ticket and that's what we return."""
    commit = commit_factory(
        "fix bug (#42) (#100)\n",
        pull_request=_make_pr(100),
    )
    assert commit.extract_issue_id() == 42


def test_update_pr_ref_dispatches_to_trailer_and_title(git_repo, commit_factory):
    _amend_message(git_repo, "fix bug\n\nbody\n")
    commit = commit_factory("fix bug\n\nbody\n")

    commit.update_pr_ref(7, "title")
    assert commit.title_pr_ref == 7

    commit.update_pr_ref(8, "trailer")
    assert commit.pr_trailer == 8


def test_update_pr_ref_rejects_unknown_mode(git_repo, commit_factory):
    _amend_message(git_repo, "fix bug\n")
    commit = commit_factory("fix bug\n")
    with pytest.raises(ValueError):
        commit.update_pr_ref(1, "bogus")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
