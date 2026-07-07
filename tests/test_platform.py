import alluvia.platform as plat


def test_candidates_cover_all_oses(monkeypatch, tmp_path):
    # only EXISTING dirs are returned
    mac = tmp_path / "Library" / "Application Support" / "Cursor"
    mac.mkdir(parents=True)
    monkeypatch.setattr(plat, "_HOME", str(tmp_path))
    monkeypatch.setattr(plat, "_WSL_USERS_GLOB", str(tmp_path / "nope" / "*"))
    roots = plat.fork_roots("Cursor")
    assert str(mac) in roots and all("nope" not in r for r in roots)


def test_claude_code_root(monkeypatch, tmp_path):
    (tmp_path / ".claude" / "projects").mkdir(parents=True)
    monkeypatch.setattr(plat, "_HOME", str(tmp_path))
    assert plat.claude_code_root() == str(tmp_path / ".claude" / "projects")
