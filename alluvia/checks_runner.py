"""Private pytest observer, executed by path in the target Python environment.

Keep this file independent of Alluvia imports: the project's environment needs
pytest, but need not have Alluvia installed. Project tests are trusted code.
"""
from __future__ import annotations

import hashlib
import importlib.abc
import importlib.machinery
import json
from pathlib import Path
import re
import sys


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _names(roots):
    names = set()
    for root in roots:
        if root.is_dir():
            for item in root.iterdir():
                if item.is_dir() and item.name.isidentifier():
                    names.add(item.name)
                elif item.suffix == ".py" and item.stem.isidentifier():
                    names.add(item.stem)
    return names


def _bounded(text):
    if len(text) > 8192:
        text = text[:8192]
        text = text.rsplit("\n", 1)[0] if "\n" in text else "[truncated]"
    # Parent process redacts normal secrets; never send it an incomplete key.
    return re.sub(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----[\s\S]*$", "[REDACTED]", text)


def main():
    import pytest

    project, root, original, relative, selector, evidence, digest = sys.argv[1:]
    project, root, original = map(Path, (project, root, original))
    test = project / relative
    roots = list(dict.fromkeys([project / "src", project, root / "src", root]))
    original_project = original / project.relative_to(root)
    owned = _names(roots + [original_project / "src", original_project,
                            original / "src", original])
    # Explicitly prefer snapshot packages even over PEP 660 editable finders
    # and regular installed packages which would beat namespace packages.
    class SnapshotImports(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if path is None and fullname.partition(".")[0] in owned:
                spec = importlib.machinery.PathFinder.find_spec(fullname, [str(p) for p in roots])
                if spec is None:
                    raise ModuleNotFoundError(f"{fullname} is absent from the selected Git snapshot")
                return spec
            return None

    sys.meta_path.insert(0, SnapshotImports())
    sys.path[:] = [str(p) for p in roots] + [p for p in sys.path if p and not (
        _inside(Path(p).resolve(), original) and not _inside(Path(p).resolve(), Path(sys.prefix)))]

    def fingerprint():
        try:
            if not _inside(test.resolve(), project) or test.is_symlink():
                return None
            return hashlib.sha256(test.read_bytes()).hexdigest()
        except OSError:
            return None

    data = {"schema_version": 1, "selected_nodeids": [], "selected_count": 0,
            "phases": [], "collection_errors": [], "test_intact": fingerprint() == digest,
            "origin_violations": [], "exit_status": None}

    class Observer:
        def pytest_collection_finish(self, session):
            data["selected_count"] = len(session.items)
            data["selected_nodeids"] = [item.nodeid for item in session.items[:20]]
            data["test_intact"] &= fingerprint() == digest

        def pytest_collectreport(self, report):
            if report.outcome != "passed" and len(data["collection_errors"]) < 20:
                data["collection_errors"].append({"nodeid": report.nodeid,
                    "outcome": report.outcome, "longrepr": _bounded(str(report.longrepr))})

        @pytest.hookimpl(hookwrapper=True)
        def pytest_runtest_makereport(self, item, call):
            result = yield
            report = result.get_result()
            data["test_intact"] &= fingerprint() == digest
            if len(data["phases"]) < 60:
                data["phases"].append({"nodeid": report.nodeid, "when": report.when,
                    "outcome": report.outcome,
                    "assertion": bool(call.excinfo and call.excinfo.errisinstance(AssertionError)),
                    "wasxfail": getattr(report, "wasxfail", None),
                    "longrepr": _bounded(str(report.longrepr)) if report.longrepr else "",
                    "duration_seconds": report.duration})

        def pytest_sessionfinish(self, session, exitstatus):
            data["exit_status"] = int(exitstatus)

    # Ignore inherited addopts and plugin entry points. Explicit project
    # conftest/plugin declarations still work, or fail visibly as unsupported.
    code = pytest.main([selector, "--rootdir", str(project), "-o", "addopts=",
                        "-o", "cache_dir=" + str(root.parent / "pytest-cache"),
                        "--basetemp", str(root.parent / "pytest-temp"), "-q", "-s"],
                       plugins=[Observer()])
    data["test_intact"] &= fingerprint() == digest
    for name, module in list(sys.modules.items()):
        filename = getattr(module, "__file__", None)
        if name != "__main__" and isinstance(filename, str):
            p = Path(filename).resolve()
            if _inside(p, original) and not _inside(p, Path(sys.prefix)):
                data["origin_violations"].append(name)
                if len(data["origin_violations"]) == 20:
                    break
    Path(evidence).write_text(json.dumps(data), encoding="utf-8")
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
