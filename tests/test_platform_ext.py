from alluvia import platform


def test_vscode_extension_dirs(tmp_path, monkeypatch):
    ext = "saoudrizwan.claude-dev"
    gs = tmp_path / "Library" / "Application Support" / "Code" / "User" / "globalStorage" / ext
    gs.mkdir(parents=True)
    monkeypatch.setattr(platform, "_HOME", str(tmp_path))
    dirs = platform.vscode_extension_dirs(ext)
    assert str(gs) in dirs


def test_vscode_extension_dirs_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(platform, "_HOME", str(tmp_path))
    assert platform.vscode_extension_dirs("nobody.nothing") == []
