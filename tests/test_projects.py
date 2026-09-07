"""Project identity: the git root a session ran in, or its cwd when no repo
is visible. Walks up on THIS machine only — a path from another machine
stays as given (still a stable key)."""
from alluvia.projects import project_root, project_key, project_name


def test_walks_up_to_the_git_root(tmp_path):
    root = tmp_path / "acme"; (root / ".git").mkdir(parents=True)
    deep = root / "src" / "pkg"; deep.mkdir(parents=True)
    assert project_root(str(deep)) == str(root)


def test_falls_back_to_cwd_when_no_repo_is_visible(tmp_path):
    d = tmp_path / "loose"; d.mkdir()
    assert project_root(str(d)) == str(d)


def test_foreign_paths_are_kept_verbatim():
    assert project_root("/home/other/box/repo/sub", isdir=lambda p: False) == "/home/other/box/repo/sub"


def test_key_and_name_are_stable():
    assert project_key("/work/acme") == project_key("/work/acme/")
    assert len(project_key("/work/acme")) == 12
    assert project_name("/work/acme/") == "acme"
    assert project_root("") is None and project_root(None) is None
