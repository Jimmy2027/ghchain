"""Tests for ghchain.commit.strip_pr_trailer (used by fix-refs)."""

from ghchain.commit import strip_pr_trailer


def test_strip_no_trailer():
    msg = "fix typo\n\nbody text"
    assert strip_pr_trailer(msg) == "fix typo\n\nbody text"


def test_strip_single_trailer():
    msg = "fix typo\n\nbody text\n\nPR: #42"
    assert strip_pr_trailer(msg) == "fix typo\n\nbody text"


def test_strip_trailer_with_trailing_newline():
    msg = "fix typo\n\nbody text\n\nPR: #42\n"
    assert strip_pr_trailer(msg) == "fix typo\n\nbody text"


def test_strip_only_removes_pr_trailer():
    """Other trailers like Signed-off-by stay; only PR: is stripped."""
    msg = "fix typo\n\nSigned-off-by: Tester <t@example.com>\nPR: #42\n"
    out = strip_pr_trailer(msg)
    assert "Signed-off-by: Tester <t@example.com>" in out
    assert "PR: #42" not in out


def test_strip_preserves_pr_in_body():
    """A `PR:` substring inside the commit body must not be stripped — it isn't a trailer."""
    msg = "fix bug\n\nThis fixes the bug from PR: #99 originally.\n"
    assert strip_pr_trailer(msg) == msg.rstrip("\n")


def test_fix_refs_lookup_matches_pre_and_post_trailer():
    """The fix-refs use case: a remote tip without the trailer must
    match a local commit with the trailer, after stripping both."""
    pre = "implement feature\n\nbody"
    post = "implement feature\n\nbody\n\nPR: #133\n"
    assert strip_pr_trailer(pre) == strip_pr_trailer(post)
