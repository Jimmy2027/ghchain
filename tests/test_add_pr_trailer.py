"""Tests for Commit.add_pr_trailer / has_pr_trailer / pr_trailer."""

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
    """Return a function that materializes a Commit on HEAD with given message."""
    from ghchain.commit import Commit

    mocker.patch.object(Commit, "update_notes")
    mocker.patch("ghchain.commit.get_workflow_status", return_value=[])
    mocker.patch("ghchain.commit.get_issue_url", return_value=None)

    def _make(message: str) -> Commit:
        head_sha = git_repo.head.commit.hexsha
        return Commit(
            sha=head_sha,
            message=message,
            branch=None,
            remote_branches=[],
            pull_request=None,
            with_workflow_status=False,
        )

    return _make


def _amend_message(repo: Repo, message: str) -> None:
    """Helper: rewrite HEAD's commit message to `message`."""
    repo.git.commit("--amend", "--no-edit", "-m", message)


def test_pr_trailer_none_when_absent(commit_factory):
    commit = commit_factory("fix typo\n\nbody text\n")
    assert commit.pr_trailer is None
    assert commit.has_pr_trailer() is False


def test_pr_trailer_parses_simple_trailer(commit_factory):
    commit = commit_factory("fix typo\n\nbody text\n\nPR: #42\n")
    assert commit.pr_trailer == 42
    assert commit.has_pr_trailer() is True


def test_pr_trailer_ignores_pr_in_body(commit_factory):
    """A `PR:` substring inside the commit body must not be parsed as a trailer."""
    msg = "fix bug\n\nThis fixes the bug discussed in PR: #99 on the old repo.\n"
    commit = commit_factory(msg)
    assert commit.pr_trailer is None


def test_add_pr_trailer_fresh_add(git_repo, commit_factory):
    """Fresh add: commit had no trailers → ends with one `PR: #N` trailer."""
    _amend_message(git_repo, "fix bug\n\nbody text\n")
    commit = commit_factory("fix bug\n\nbody text\n")

    old_sha = commit.sha
    new_sha = commit.add_pr_trailer(7)

    assert new_sha != old_sha
    assert commit.sha == new_sha
    assert commit.pr_trailer == 7
    head_msg = git_repo.git.log("-1", "--format=%B", "HEAD")
    assert "PR: #7" in head_msg


def test_add_pr_trailer_replaces_existing(git_repo, commit_factory):
    """Replace: commit had `PR: #99` → ends with the new number, only one trailer."""
    msg = "fix bug\n\nbody\n\nPR: #99\n"
    _amend_message(git_repo, msg)
    commit = commit_factory(msg)

    new_sha = commit.add_pr_trailer(7)

    assert commit.pr_trailer == 7
    head_msg = git_repo.git.log("-1", "--format=%B", "HEAD")
    # Should not contain the stale trailer anymore.
    assert "PR: #99" not in head_msg
    assert head_msg.count("PR: #7") == 1
    assert commit.sha == new_sha


def test_add_pr_trailer_noop_when_matching(git_repo, commit_factory):
    """No-op: add_pr_trailer(N) on a commit with PR: #N already produces no new SHA."""
    msg = "fix bug\n\nbody\n\nPR: #7\n"
    _amend_message(git_repo, msg)
    commit = commit_factory(msg)

    sha_before = commit.sha
    returned = commit.add_pr_trailer(7)

    assert returned == sha_before
    assert commit.sha == sha_before


def test_add_pr_trailer_preserves_other_trailers(git_repo, commit_factory):
    """Other trailers in the block (Signed-off-by, etc.) must survive the amend."""
    msg = "fix bug\n\nbody\n\nSigned-off-by: Test User <test@example.com>\n"
    _amend_message(git_repo, msg)
    commit = commit_factory(msg)

    commit.add_pr_trailer(11)

    head_msg = git_repo.git.log("-1", "--format=%B", "HEAD")
    assert "Signed-off-by: Test User <test@example.com>" in head_msg
    assert "PR: #11" in head_msg


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
