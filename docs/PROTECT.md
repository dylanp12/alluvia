# Protect a corrected behavior

Turn a correction into one pytest test, then check that it catches the old
behavior and passes after the fix. Alluvia exports the test with a receipt
showing its source, the two commits, and the observed results. The exported
test uses your project's normal test runner; it has no Alluvia dependency.

This first version supports Python projects with pytest and two committed
Git revisions. It uses your existing test environment. It does not install
dependencies or create a fix for you.

## In Claude Code

Install the CLI and plugin if you have not already:

```bash
uv tool install alluvia
```

Then, in Claude Code:

```text
/plugin marketplace add dylanp12/alluvia
/plugin install alluvia@alluvia
/alluvia:protect Uploads must be smaller than 8 MiB; exactly 8 MiB must be rejected.
```

Already installed Alluvia? Update both the CLI and plugin from your terminal:

```bash
uv tool upgrade alluvia
claude plugin update alluvia@alluvia
```

Restart Claude Code to load the updated plugin, then invoke `/alluvia:protect`.

The skill asks your agent to identify the requirement and its source, locate
the buggy and fixed commits, write one focused test, and run the verifier.
It preserves existing tests and reports incomplete evidence. Inspect the
proposed assertion and receipt before keeping the test in your suite.

A current instruction is enough to start. You do not need to run `alluvia
init`, refresh your history, sign in, or configure another model provider.
Your host agent still uses its normal account and permissions.

## Run the verifier directly

Start with a fix already committed to Git and a Python environment that can
run the project with pytest. Write a new test file in your working directory.
The test itself may be uncommitted; the application code in both runs comes
from the specified commits.

For a current instruction, save its exact wording and attribution in JSON:

```json
{
  "kind": "user_instruction",
  "text": "Uploads must be smaller than 8 MiB; exactly 8 MiB must be rejected."
}
```

Save this as `correction-source.json`. From the project directory, run:

```bash
alluvia checks verify 'tests/test_upload_policy.py::test_upload_limit_is_exclusive' \
  --before HEAD^ \
  --after HEAD \
  --project . \
  --requirement 'Reject uploads of exactly 8 MiB while accepting smaller uploads.' \
  --source-file correction-source.json \
  --python .venv/bin/python \
  --timeout 60 \
  --output ./upload-limit-check
```

Replace `HEAD^` with the revision containing the bug and `HEAD` with the
revision containing the fix. The example assumes the fix is the latest
commit and its parent contains the bug. Refs are resolved to full commit IDs
in the receipt. Changes that exist only in your working tree are not included
in either application snapshot.

`--python` selects an existing interpreter with pytest and the project's
dependencies; on Windows, a typical virtual environment uses
`.venv\Scripts\python.exe`. Select an environment compatible with both
revisions. Alluvia does not install either revision. Projects needing generated
or untracked files may need additional preparation; an import or setup error
cannot verify the check.

This version rejects snapshots containing symbolic links or hard links. It
also disables automatic discovery of installed pytest plugins; plugins
explicitly declared in a committed `conftest.py` remain supported. If your
test depends on an automatically loaded plugin, inspect that prerequisite
before treating a failed or skipped run as evidence.

The selector must identify exactly one test. Quote parameterized selectors
and include their case ID if needed. Paths are relative to `--project`, which
may point to a subdirectory of a Git repository. Use an output directory that
does not exist; Alluvia refuses to overwrite an earlier bundle.

## Use a captured source

If the correction is already in Alluvia, export its source receipt:

```bash
alluvia checks source NOTE_ID --project . > correction-source.json
```

Replace `NOTE_ID` with the relevant note ID and inspect the file before
verification. The source command checks the project scope and rejects
suppressed notes and injected harness content. It includes the source role,
quote, span, hash, and session reference; a shortened quote is marked as such.
Assistant text remains attributed to the assistant.

The verifier preserves the supplied source as evidence. A JSON attribution
is not independent proof of who said it. Review the source and requirement
together; a previous suggestion may not be the instruction you want to protect.

## Read the result

The verifier freezes the test bytes once and runs them against separate,
temporary snapshots of the two commits. It does not switch your checkout or
rewrite your test. Each run records the selected test, its setup/call/teardown
outcomes, process result, and duration. The bundle contains the unchanged test,
a JSON receipt, and a readable report with commands and limitations.

The exported files are `test/<original-test-path>`, `report.json`, and
`README.md`. The test retains its original imports and fixture requirements;
keep its path and supporting project files when adding it to your suite.

| Status | Meaning |
| --- | --- |
| `verified` | The same single test failed by assertion in its call phase before the fix and passed all phases afterward, with normal pytest completion and unchanged test bytes. |
| `not_verified` | The test passed in both revisions or failed by assertion in both. It has not demonstrated the required difference. |
| `inconclusive` | The run could not establish the result: for example an import/setup error, skip, xfail, timeout, missing evidence, extra tests, or a modified test. |

The CLI emits JSON and exits with `0` for verified, `1` for not verified or
inconclusive, and `2` for an invalid request.

Red/green demonstrates that this test distinguishes these two revisions.
It does not establish that the assertion expresses the requirement correctly,
that every behavior is covered, or that future changes will preserve the
behavior. Read the failure and add the exported test to your normal suite.

Tests execute as your user, with the same filesystem, network, and credential
access as a normal pytest run. Temporary snapshots separate code versions;
they are not a security sandbox. Run this workflow only on code you trust.

For a complete example with a small repository and no historical commit IDs
to look up, see the [upload-limit demo](examples/protect/README.md).
