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


def test_foreign_paths_are_verbatim_not_normalized():
    """A path recorded on another machine (or OS) is an opaque key: never
    collapse, re-separate, or otherwise rewrite it. Only a trailing separator
    is dropped so 'x/' and 'x' agree."""
    assert project_root("/home/other/box//repo/./sub", isdir=lambda p: False) == "/home/other/box//repo/./sub"
    assert project_root("C:\\Users\\x\\repo\\", isdir=lambda p: False) == "C:\\Users\\x\\repo"


def test_key_and_name_agree_across_separators():
    assert project_key("C:\\work\\acme") == project_key("C:/work/acme") == project_key("C:/work/acme/")
    assert project_name("C:\\work\\acme") == "acme"
