"""Verify one ordinary pytest check against two committed Git snapshots.

Tests execute with the caller's privileges. Isolation protects the caller's
checkout from normal test edits; it is not a security sandbox for hostile code.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time

from alluvia.distill.scrub import redact

LOG_LIMIT = 65536
ARCHIVE_LIMIT = 128 * 1024 * 1024
TEST_LIMIT = 1024 * 1024


class CheckError(ValueError):
    """The supplied request cannot be safely or meaningfully verified."""


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _redact(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: _redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _log_text(raw, truncated):
    text = raw.decode("utf-8", "replace")
    if truncated:
        # Dropping the partial last line avoids retaining half of a secret
        # whose remaining bytes fell beyond the output limit.
        text = text.rsplit("\n", 1)[0] if "\n" in text else ""
    text = redact(text)
    # A multi-line key may itself extend beyond the retained output.
    return re.sub(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----[\s\S]*$", "[REDACTED]", text)


def _kill_tree(process):
    # Existing dependency; also catch ordinary descendants which started their
    # own process group before the timeout. No shell command is involved.
    import psutil
    try:
        children = psutil.Process(process.pid).children(recursive=True)
    except psutil.Error:
        children = []
    for child in reversed(children):
        try:
            child.kill()
        except psutil.Error:
            pass
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif process.poll() is None:
        process.kill()
    if children:
        psutil.wait_procs(children, timeout=0.2)


def _process(argv, cwd, timeout, *, env=None, archive=None, raw_stdout=False):
    started = time.monotonic()
    kwargs = {"start_new_session": True} if os.name == "posix" else {}
    try:
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    except OSError as exc:
        raise CheckError(f"Cannot start {argv[0]}: {exc}") from exc
    captured = [bytearray(), bytearray()]
    truncated = [False, False]
    overflow = threading.Event()

    def drain(pipe, index):
        total = 0
        try:
            while chunk := pipe.read(8192):
                total += len(chunk)
                limit = ARCHIVE_LIMIT if archive is not None and index == 0 else LOG_LIMIT
                if total > limit:
                    truncated[index] = True
                if archive is not None and index == 0:
                    if total > limit:
                        overflow.set()
                    else:
                        archive.write(chunk)
                else:
                    remaining = limit - len(captured[index])
                    if remaining > 0:
                        captured[index].extend(chunk[:remaining])
        finally:
            pipe.close()

    threads = [threading.Thread(target=drain, args=(pipe, i), daemon=True)
               for i, pipe in enumerate((process.stdout, process.stderr))]
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        while process.poll() is None:
            if time.monotonic() - started >= timeout or overflow.is_set():
                timed_out = not overflow.is_set()
                _kill_tree(process)
                break
            time.sleep(0.02)
        process.wait(timeout=5)
    finally:
        _kill_tree(process)  # Close any ordinary descendants left after exit.
        for thread in threads:
            thread.join(timeout=2)
    return {"command": list(map(str, argv)), "returncode": process.returncode,
            "timed_out": timed_out, "duration_seconds": round(time.monotonic() - started, 4),
            "stdout": (captured[0].decode("utf-8", "replace") if raw_stdout
                       else _log_text(captured[0], truncated[0])),
            "stderr": _log_text(captured[1], truncated[1]),
            "output_truncated": any(truncated), "archive_too_large": overflow.is_set()}


def _git(root, *args):
    result = _process(["git", "-C", str(root), *args], root, 30, raw_stdout=True)
    if result["returncode"] != 0 or result["timed_out"]:
        raise CheckError("Git could not resolve the request: " + result["stderr"][:1000])
    return result["stdout"].strip()


def _commit(root, ref):
    if not isinstance(ref, str) or not ref.strip() or ref.startswith("-") or any(c in ref for c in "\n\r\0"):
        raise CheckError("Git references must be nonempty revision names, not options")
    return _git(root, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}")


def _snapshot(root, commit, destination):
    destination.mkdir()
    with tempfile.TemporaryFile() as archive:
        result = _process(["git", "-C", str(root), "archive", "--format=tar", commit],
                          root, 30, archive=archive)
        if result["returncode"] or result["timed_out"] or result["archive_too_large"]:
            raise CheckError("Cannot create bounded Git snapshot: " + result["stderr"][:1000])
        archive.seek(0)
        try:
            with tarfile.open(fileobj=archive, mode="r:") as tar:
                members = tar.getmembers()
                if len(members) > 20000 or sum(m.size for m in members) > ARCHIVE_LIMIT:
                    raise CheckError("Git snapshot exceeds the 128 MiB / 20,000-file limit")
                for member in members:
                    path = PurePosixPath(member.name)
                    if (path.is_absolute() or ".." in path.parts or "\\" in member.name
                            or ":" in member.name or not (member.isdir() or member.isfile())):
                        raise CheckError("Unsupported archive path or link: " + member.name[:200])
                for member in members:
                    target = destination / member.name
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with tar.extractfile(member) as src, target.open("xb") as dst:
                            shutil.copyfileobj(src, dst)
                        target.chmod(member.mode & 0o777)
        except (tarfile.TarError, OSError) as exc:
            raise CheckError(f"Cannot extract Git snapshot: {exc}") from exc


def _run_side(root, project_rel, commit, relative, selector, frozen, python, timeout, directory):
    snapshot = directory / "repo"
    _snapshot(root, commit, snapshot)
    project = snapshot / project_rel
    if not project.is_dir():
        raise CheckError("Project path does not exist in both Git revisions")
    test = project / relative
    test.parent.mkdir(parents=True, exist_ok=True)
    test.write_bytes(frozen)
    digest = hashlib.sha256(frozen).hexdigest()
    evidence = directory / "evidence.json"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "PYTEST", "COV_CORE", "GIT_"))}
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    helper = Path(__file__).with_name("checks_runner.py")
    argv = [python, "-I", str(helper), str(project), str(snapshot), str(root),
            relative, selector, str(evidence), digest]
    process = _process(argv, project, timeout, env=env)
    data = {}
    try:
        if evidence.stat().st_size <= 2 * 1024 * 1024:
            loaded = json.loads(evidence.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
    except (OSError, ValueError):
        pass
    intact = test.is_file() and not test.is_symlink() and _inside(test.resolve(), project)
    if intact:
        intact = test.stat().st_size == len(frozen) and test.read_bytes() == frozen
    return {"commit": commit, **process, "selected_nodeids": data.get("selected_nodeids", []),
            "selected_count": data.get("selected_count", 0), "phases": data.get("phases", []),
            "collection_errors": data.get("collection_errors", []),
            "origin_violations": data.get("origin_violations", []),
            "test_intact": bool(intact and data.get("test_intact")),
            "evidence_complete": data.get("schema_version") == 1 and data.get("exit_status") == process["returncode"]}


def _outcome(side, selector):
    if (side["timed_out"] or not side["evidence_complete"] or not side["test_intact"]
            or side["collection_errors"] or side["origin_violations"] or side["selected_count"] != 1
            or len(side["selected_nodeids"]) != 1):
        return None
    selected = side["selected_nodeids"][0]
    if selected != selector and not selected.startswith(selector + "["):
        return None
    phases = side["phases"]
    if (len(phases) != 3 or [p.get("when") for p in phases] != ["setup", "call", "teardown"]
            or any(p.get("nodeid") != side["selected_nodeids"][0] or p.get("wasxfail") is not None for p in phases)
            or phases[0].get("outcome") != "passed" or phases[2].get("outcome") != "passed"):
        return None
    if phases[1].get("outcome") == "passed" and side["returncode"] == 0:
        return "passed"
    if phases[1].get("outcome") == "failed" and phases[1].get("assertion") and side["returncode"] == 1:
        return "assertion_failed"
    return None


def _export(output, report, frozen, relative):
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.mkdir()  # Refuse existing files/directories, including a race.
    except OSError as exc:
        raise CheckError(f"Cannot create a new output directory: {exc}") from exc
    artifact = Path("test") / relative
    report["artifacts"] = {"test": artifact.as_posix(), "report": "report.json", "readme": "README.md"}
    target = output / artifact
    target.parent.mkdir(parents=True)
    target.write_bytes(frozen)
    (output / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = ["# Alluvia regression check", "", f"Status: **{report['status']}**", "",
             report["reason"], "", "## Requirement and supplied source", "",
             report["requirement"], "", "```json", json.dumps(report["source"], indent=2), "```", "",
             "The source is supplied evidence, not independently authenticated authority.", "",
             "## Exported test", "", f"Copy `{artifact.as_posix()}` to `{relative}` in the corrected project.",
             "This is an ordinary project test; it does not require the Alluvia verifier to run.", "",
             f"Frozen test SHA-256: `{report['test']['sha256']}`", "", "## Executions", ""]
    for name in ("before", "after"):
        side = report[name]
        lines += [f"### {name}: `{side['commit']}`", "", f"Exit: {side['returncode']}; timeout: {side['timed_out']}",
                  "", "Exact subprocess argv (temporary snapshot paths no longer exist):", "```json",
                  json.dumps(side["command"]), "```", ""]
    lines += ["## Limits", "", "This is not a security sandbox. Trusted project tests ran with the caller's privileges.",
              "Red/green shows this check distinguishes these committed revisions, not complete semantic correctness.",
              "Inspect the assertion and source. Setup errors, skips, xfails and missing evidence never count as protection.",
              "Snapshots contain committed files plus the identical test. Other uncommitted work is excluded.",
              "The same Python environment was used on both sides; dependency installation and automatic plugin discovery were disabled.",
              "Recognized secrets are redacted from evidence, but the exported test is byte-identical: inspect it before sharing.", ""]
    (output / "README.md").write_text("\n".join(lines), encoding="utf-8")


def verify_check(project, selector, before, after="HEAD", *, requirement, source,
                 python=None, timeout=60, output=None) -> dict:
    """Return evidence for a single pytest test; optionally export without overwrites.

    Both code states are commits. The selected test is frozen from the current
    project, including uncommitted bytes. Unsupported requests raise CheckError;
    executed checks return verified, not_verified, or inconclusive. Relative
    Python paths are interpreted from the caller's current directory.
    """
    if not isinstance(requirement, str) or not requirement.strip() or len(requirement) > 10000:
        raise CheckError("A nonempty requirement of at most 10,000 characters is required")
    if not isinstance(source, dict) or any(not isinstance(source.get(k), str) or not source[k].strip() for k in ("kind", "text")):
        raise CheckError("Source must contain nonempty kind and text strings")
    try:
        if len(json.dumps(source, allow_nan=False)) > 65536:
            raise CheckError("Source receipt exceeds 64 KiB")
    except (TypeError, ValueError) as exc:
        raise CheckError(f"Source must be bounded JSON: {exc}") from exc
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 1 <= timeout <= 600:
        raise CheckError("Timeout must be between 1 and 600 seconds per revision")
    if not isinstance(selector, str) or "::" not in selector or any(c in selector for c in "\r\n\0"):
        raise CheckError("Select one relative Python file and test: path.py::test_name")
    relative, name = selector.split("::", 1)
    path = PurePosixPath(relative)
    if (not name or not relative or path.is_absolute() or ".." in path.parts or "\\" in relative
            or ":" in relative or path.suffix != ".py" or relative.startswith("-")):
        raise CheckError("The test path must stay inside the project without traversal")
    relative = path.as_posix()
    selector = relative + "::" + name
    project = Path(project).resolve()
    if not project.is_dir():
        raise CheckError("Project must be an existing directory")
    test = project / relative
    if not test.is_file() or test.is_symlink() or not _inside(test.resolve(), project):
        raise CheckError("Selected test must be a regular file within the project")
    if test.stat().st_size > TEST_LIMIT:
        raise CheckError("Selected test exceeds 1 MiB")
    frozen = test.read_bytes()
    root = Path(_git(project, "rev-parse", "--show-toplevel")).resolve()
    if not _inside(project, root):
        raise CheckError("Project must be inside its Git checkout")
    commits = (_commit(root, before), _commit(root, after))
    executable = shutil.which(str(python or sys.executable))
    if not executable:
        raise CheckError("Python executable was not found")
    # Snapshot subprocesses change cwd. Preserve the caller's path and its venv
    # symlink: resolving that symlink could select the base Python environment.
    executable = str(Path(executable).absolute())
    destination = Path(output).absolute() if output is not None else None
    if destination is not None and os.path.lexists(destination):
        raise CheckError("Output path already exists; choose a new directory")
    with tempfile.TemporaryDirectory(prefix="alluvia-check-") as temp:
        # macOS /var aliases and Windows short paths must match pytest's cwd
        # and the resolved paths used for test-integrity checks.
        temp_root = Path(temp).resolve()
        sides = []
        for label, commit in zip(("before", "after"), commits):
            directory = temp_root / label
            directory.mkdir()
            sides.append(_run_side(root, project.relative_to(root), commit, relative,
                                   selector, frozen, executable, timeout, directory))
    old, new = (_outcome(side, selector) for side in sides)
    if old is None or new is None or sides[0]["selected_nodeids"] != sides[1]["selected_nodeids"]:
        status, reason = "inconclusive", "A run lacked one intact test with normal setup, call and teardown evidence. Inspect both runs."
    elif old == "assertion_failed" and new == "passed":
        status, reason = "verified", "The same test had an assertion failure before and passed after. Inspect the assertion and source before accepting its meaning."
    else:
        status, reason = "not_verified", "The check did not demonstrate an assertion failure before followed by a pass after."
    report = _redact({"schema_version": 1, "status": status, "reason": reason,
                     "requirement": requirement, "source": source, "before": sides[0], "after": sides[1],
                     "test": {"path": relative, "selector": selector, "sha256": hashlib.sha256(frozen).hexdigest()}})
    if destination is not None:
        _export(destination, report, frozen, relative)
    return report
