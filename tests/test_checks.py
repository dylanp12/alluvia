"""A red/green claim requires real, isolated executions of the same test."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest


SOURCE = {"kind": "user_instruction", "text": "Expire snapshots after 20 minutes."}
GUARD = "from retention import LIMIT\n\ndef test_guard():\n    assert LIMIT == 20\n"


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          text=True, capture_output=True).stdout.strip()


def history(tmp_path, nested="", before="LIMIT = 45\n", after="LIMIT = 20\n"):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    project = root / nested
    project.mkdir(parents=True, exist_ok=True)
    (project / "retention.py").write_text(before)
    git(root, "add", ".")
    git(root, "commit", "-qm", "old behavior")
    old = git(root, "rev-parse", "HEAD")
    (project / "retention.py").write_text(after)
    git(root, "add", ".")
    git(root, "commit", "--allow-empty", "-qm", "corrected behavior")
    new = git(root, "rev-parse", "HEAD")
    (project / "tests").mkdir()
    (project / "tests" / "test_guard.py").write_text(GUARD)
    return root, project, old, new


def verify(project, before, after, **kwargs):
    from alluvia.checks import verify_check
    return verify_check(project, kwargs.pop("selector", "tests/test_guard.py::test_guard"),
                        before, after, requirement="Use 20 minutes", source=SOURCE,
                        python=sys.executable, **kwargs)


def test_exports_a_real_assertion_failure_then_pass_without_changing_checkout(tmp_path):
    root, project, before, after = history(tmp_path)
    frozen = (project / "tests/test_guard.py").read_bytes()
    (project / "retention.py").write_text("LIMIT = 999  # uncommitted\n")
    original_status = git(root, "status", "--porcelain")
    out = tmp_path / "proof"

    report = verify(project, before, after, output=out)

    assert report["status"] == "verified", report
    assert report["before"]["commit"] == before
    assert report["after"]["commit"] == after
    assert report["before"]["returncode"] == 1
    assert report["after"]["returncode"] == 0
    assert report["before"]["selected_nodeids"] == ["tests/test_guard.py::test_guard"]
    assert any(p["when"] == "call" and p["assertion"] for p in report["before"]["phases"])
    assert report["test"]["sha256"] == hashlib.sha256(frozen).hexdigest()
    assert (out / report["artifacts"]["test"]).read_bytes() == frozen
    assert (project / "tests/test_guard.py").read_bytes() == frozen
    assert json.loads((out / "report.json").read_text()) == report
    assert "not a security sandbox" in (out / "README.md").read_text().lower()
    assert git(root, "status", "--porcelain") == original_status
    assert git(root, "rev-parse", "HEAD") == after
    assert (project / "retention.py").read_text() == "LIMIT = 999  # uncommitted\n"


@pytest.mark.parametrize("before,after", [(20, 20), (45, 45)])
def test_no_distinguishing_result_is_not_verified(tmp_path, before, after):
    _, project, old, new = history(tmp_path, before=f"LIMIT = {before}\n", after=f"LIMIT = {after}\n")
    assert verify(project, old, new)["status"] == "not_verified"


@pytest.mark.parametrize("test_text", [
    "import missing_dependency_for_guard\n\ndef test_guard():\n    assert True\n",
    "import pytest\n\n@pytest.fixture(autouse=True)\ndef setup():\n    assert False\n\ndef test_guard():\n    assert True\n",
    "import pytest\n\ndef test_guard():\n    pytest.skip('not supported')\n",
    "import pytest\n\n@pytest.mark.xfail(reason='not fixed')\ndef test_guard():\n    assert False\n",
    "import pytest\n\n@pytest.mark.xfail(reason='unexpected pass')\ndef test_guard():\n    assert True\n",
    "def test_guard():\n    raise ValueError('not an assertion')\n",
    "import pytest\n\n@pytest.fixture(autouse=True)\ndef cleanup():\n    yield\n    assert False\n\ndef test_guard():\n    assert True\n",
    "import pytest\n\n@pytest.mark.parametrize('value', [1,2])\ndef test_guard(value):\n    assert value == 1\n",
    "def test_different_name():\n    assert True\n",
])
def test_non_assertion_or_incomplete_execution_is_inconclusive(tmp_path, test_text):
    _, project, old, new = history(tmp_path)
    (project / "tests/test_guard.py").write_text(test_text)
    assert verify(project, old, new)["status"] == "inconclusive"


def test_test_mutation_is_inconclusive_and_original_bytes_are_exported(tmp_path):
    _, project, old, new = history(tmp_path)
    body = "from pathlib import Path\nfrom retention import LIMIT\n\ndef test_guard():\n    Path(__file__).write_text('# changed')\n    assert LIMIT == 20\n"
    (project / "tests/test_guard.py").write_text(body)
    report = verify(project, old, new, output=tmp_path / "proof")
    assert report["status"] == "inconclusive"
    assert not report["before"]["test_intact"]
    assert (tmp_path / "proof" / report["artifacts"]["test"]).read_text() == body
    assert (project / "tests/test_guard.py").read_text() == body


def test_nested_project_and_src_layout_use_snapshot_imports(tmp_path, monkeypatch):
    root, project, old, new = history(tmp_path, nested="packages/service")
    monkeypatch.setenv("PYTHONPATH", str(project))
    assert verify(project, old, new)["status"] == "verified"
    # A src layout must work even though the caller's checkout is on the fix.
    git(root, "reset", "--hard", old)
    (project / "src").mkdir()
    (project / "retention.py").rename(project / "src/retention.py")
    git(root, "add", ".")
    git(root, "commit", "-qm", "src old")
    old = git(root, "rev-parse", "HEAD")
    (project / "src/retention.py").write_text("LIMIT = 20\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "src fixed")
    new = git(root, "rev-parse", "HEAD")
    assert verify(project, old, new)["status"] == "verified"


def test_uncommitted_dependency_is_not_imported_from_original_checkout(tmp_path, monkeypatch):
    _, project, old, new = history(tmp_path)
    (project / "uncommitted_helper.py").write_text("VALUE = 20\n")
    monkeypatch.setenv("PYTHONPATH", str(project))
    (project / "tests/test_guard.py").write_text("from uncommitted_helper import VALUE\n\ndef test_guard():\n    assert VALUE == 20\n")
    assert verify(project, old, new)["status"] == "inconclusive"


@pytest.mark.parametrize("selector", ["tests/test_guard.py", "../outside.py::test_guard", "/tmp/guard.py::test_guard", "tests/../tests/test_guard.py::test_guard"])
def test_unsafe_or_incomplete_selectors_are_rejected(tmp_path, selector):
    from alluvia.checks import CheckError
    _, project, old, new = history(tmp_path)
    with pytest.raises(CheckError):
        verify(project, old, new, selector=selector)


def test_symlink_test_and_unsafe_committed_symlinks_are_rejected(tmp_path):
    from alluvia.checks import CheckError
    root, project, old, new = history(tmp_path)
    external = tmp_path / "external.py"
    external.write_text(GUARD)
    (project / "tests/test_guard.py").unlink()
    (project / "tests/test_guard.py").symlink_to(external)
    with pytest.raises(CheckError):
        verify(project, old, new)
    (project / "tests/test_guard.py").unlink()
    (project / "tests/test_guard.py").write_text(GUARD)
    (root / "escape").symlink_to(tmp_path, target_is_directory=True)
    git(root, "add", "escape")
    git(root, "commit", "-qm", "unsafe link")
    with pytest.raises(CheckError):
        verify(project, old, "HEAD")


def test_invalid_refs_output_collision_and_runtime_bounds_are_rejected(tmp_path):
    from alluvia.checks import CheckError
    _, project, old, new = history(tmp_path)
    for options in ({"before": "no-such-ref"}, {"before": "--help"}, {"timeout": 0}, {"timeout": 601}):
        before = options.pop("before", old)
        with pytest.raises(CheckError):
            verify(project, before, new, **options)
    out = tmp_path / "existing"
    out.mkdir()
    (out / "keep").write_text("precious")
    with pytest.raises(CheckError):
        verify(project, old, new, output=out)
    assert (out / "keep").read_text() == "precious"


def test_timeout_kills_descendant_process_and_bounds_wait(tmp_path):
    import psutil
    _, project, old, new = history(tmp_path)
    pid_file = tmp_path / "child-pids"
    body = ("import subprocess, sys, time\nfrom pathlib import Path\n\ndef test_guard():\n"
            "    p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
            f"    with Path({str(pid_file)!r}).open('a') as f: f.write(str(p.pid) + '\\n')\n"
            "    time.sleep(30)\n")
    (project / "tests/test_guard.py").write_text(body)
    started = time.monotonic()
    report = verify(project, old, new, timeout=1)
    assert time.monotonic() - started < 10
    assert report["status"] == "inconclusive"
    assert report["before"]["timed_out"]
    assert pid_file.exists(), "test did not start its child before timeout"
    for pid in map(int, pid_file.read_text().splitlines()):
        assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE


def test_output_is_bounded_and_recognized_secrets_are_redacted(tmp_path):
    from alluvia.checks import verify_check
    _, project, old, new = history(tmp_path)
    secret = "sk-" + "a" * 24
    (project / "tests/test_guard.py").write_text(
        f"import os\nfrom retention import LIMIT\n\ndef test_guard():\n    os.write(1, ({secret!r} + 'x' * 100000).encode())\n    assert LIMIT == 20\n")
    report = verify_check(project, "tests/test_guard.py::test_guard", old, new,
                          requirement="Use 20", source={"kind": "user_instruction", "text": secret}, python=sys.executable)
    assert report["status"] == "verified", report
    assert secret not in json.dumps(report)
    assert len(report["before"]["stdout"]) <= 65536


def test_requires_an_attributed_nonempty_source(tmp_path):
    from alluvia.checks import CheckError, verify_check
    _, project, old, new = history(tmp_path)
    for source in ({}, {"kind": "user_instruction", "text": ""}):
        with pytest.raises(CheckError):
            verify_check(project, "tests/test_guard.py::test_guard", old, new,
                         requirement="Use 20", source=source)


def test_pytest_cannot_redirect_the_selector_to_another_function(tmp_path):
    root, project, _, _ = history(tmp_path)
    (project / "conftest.py").write_text(
        "def pytest_collection_modifyitems(items):\n"
        "    for item in items:\n"
        "        item._nodeid = 'tests/test_guard.py::test_other'\n")
    (project / "retention.py").write_text("LIMIT = 45\n")
    git(root, "add", "conftest.py", "retention.py")
    git(root, "commit", "-qm", "old with collection hook")
    old = git(root, "rev-parse", "HEAD")
    (project / "retention.py").write_text("LIMIT = 20\n")
    git(root, "add", "retention.py")
    git(root, "commit", "-qm", "new with collection hook")
    report = verify(project, old, "HEAD")
    assert report["status"] == "inconclusive", report


def test_error_logs_cannot_leak_a_secret_split_at_the_retention_boundary(tmp_path):
    _, project, old, new = history(tmp_path)
    # Retaining a prefix may split a token below the redactor's minimum length.
    (project / "tests/test_guard.py").write_text(
        "import os\nfrom retention import LIMIT\n\ndef test_guard():\n"
        "    os.write(1, b'x' * 65521 + b'sk-' + b'a' * 24)\n"
        "    assert LIMIT == 20\n")
    report = verify(project, old, new)
    assert "sk-aaaa" not in report["before"]["stdout"]


def test_editable_meta_path_finder_does_not_override_the_snapshot(tmp_path):
    import sysconfig
    import venv
    from alluvia.checks import verify_check

    _, project, old, new = history(tmp_path)
    env = tmp_path / "venv"
    venv.EnvBuilder(with_pip=False, symlinks=os.name != "nt").create(env)
    executable = env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    purelib = subprocess.run([str(executable), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
                             capture_output=True, text=True, check=True).stdout.strip()
    site = Path(purelib)
    (site / "dependencies.pth").write_text(sysconfig.get_path("purelib") + "\n")
    (site / "fixture_editable.py").write_text(
        "import sys, importlib.util\n"
        "class Finder:\n"
        "    def find_spec(self, fullname, path=None, target=None):\n"
        "        if fullname == 'retention':\n"
        f"            return importlib.util.spec_from_file_location(fullname, {str(project / 'retention.py')!r})\n"
        "sys.meta_path.insert(0, Finder())\n")
    (site / "editable.pth").write_text("import fixture_editable\n")
    report = verify_check(project, "tests/test_guard.py::test_guard", old, new,
                          requirement="Use 20 minutes", source=SOURCE, python=executable)
    assert report["status"] == "verified", report


def test_display_redaction_does_not_change_the_actual_git_path(tmp_path):
    parent = tmp_path / "fixture@example.invalid workspace"
    parent.mkdir()
    _, project, old, new = history(parent)
    assert verify(project, old, new)["status"] == "verified"


@pytest.mark.parametrize("caller_is_project", [True, False])
def test_relative_python_uses_the_callers_directory_and_preserves_venv(tmp_path, monkeypatch, caller_is_project):
    import sysconfig
    import venv
    from alluvia.checks import verify_check

    _, project, old, new = history(tmp_path, nested="packages/service")
    caller = project if caller_is_project else tmp_path
    env = caller / ".venv"
    venv.EnvBuilder(with_pip=False, symlinks=os.name != "nt").create(env)
    relative_python = Path(".venv") / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    executable = caller / relative_python
    purelib = subprocess.run([str(executable), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
                             capture_output=True, text=True, check=True).stdout.strip()
    site = Path(purelib)
    (site / "dependencies.pth").write_text(sysconfig.get_path("purelib") + "\n")
    # Only this venv contains this module: resolving its Python symlink would
    # silently switch environments and turn the intended proof inconclusive.
    (site / "fixture_environment_only.py").write_text("VALUE = 20\n")
    (project / "tests/test_guard.py").write_text(
        "from fixture_environment_only import VALUE\nfrom retention import LIMIT\n\n"
        "def test_guard():\n    assert LIMIT == VALUE\n")
    monkeypatch.chdir(caller)

    report = verify_check(project, "tests/test_guard.py::test_guard", old, new,
                          requirement="Use 20 minutes", source=SOURCE, python=relative_python)

    assert report["status"] == "verified", report
    assert report["before"]["command"][0] == str(executable)
