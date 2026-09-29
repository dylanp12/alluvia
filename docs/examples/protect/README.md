# Upload-limit example

This example protects one correction: **uploads must be smaller than 8 MiB**.
The old implementation accepts exactly 8 MiB; the fix rejects it. One test
checks both the boundary and the largest accepted size.

Prerequisites: Alluvia with `alluvia checks verify`, Git, and Python with
pytest already installed. The commands use a Bash-compatible shell. Activate
your existing Python test environment before starting; no dependency is
installed by the demo or verifier.

The commands create a temporary Git repository and leave your current project
untouched. The source JSON is an example instruction supplied with the demo,
not a recovered conversation.

## Create the two revisions and the test

Copy this block into your shell:

```bash
protect_python="$(python -c 'import sys; print(sys.executable)')"
"$protect_python" -m pytest --version
alluvia checks verify --help

protect_demo="$(mktemp -d)"
cd "$protect_demo"
git init -q
git config user.name 'Protect Example'
git config user.email 'protect@example.com'

cat > upload_policy.py <<'PY'
def accepts_upload(size):
    return size <= 8 * 1024 * 1024
PY
git add upload_policy.py
git -c commit.gpgsign=false commit -qm 'Accept uploads up to the limit'

cat > test_upload_policy.py <<'PY'
from upload_policy import accepts_upload


def test_upload_limit_is_exclusive():
    limit = 8 * 1024 * 1024
    assert accepts_upload(limit - 1)
    assert not accepts_upload(limit)
PY

# Expected: one assertion failure at exactly 8 MiB.
"$protect_python" -m pytest -q test_upload_policy.py::test_upload_limit_is_exclusive

cat > upload_policy.py <<'PY'
def accepts_upload(size):
    return size < 8 * 1024 * 1024
PY
git add upload_policy.py
git -c commit.gpgsign=false commit -qm 'Reject uploads at the limit'

# Expected: one passing test. The test itself remains uncommitted.
"$protect_python" -m pytest -q test_upload_policy.py::test_upload_limit_is_exclusive

cat > correction-source.json <<'JSON'
{
  "kind": "user_instruction",
  "text": "Uploads must be smaller than 8 MiB; exactly 8 MiB must be rejected."
}
JSON
```

The first pytest command intentionally exits with `1`. If your shell stops
on errors, run through that command first, then run the remaining commands.
The test must fail at `assert not accepts_upload(limit)`, not during import
or setup.

## Verify and export

In the same shell and directory, run:

```bash
alluvia checks verify 'test_upload_policy.py::test_upload_limit_is_exclusive' \
  --before HEAD^ \
  --after HEAD \
  --project . \
  --requirement 'Reject uploads of exactly 8 MiB while accepting smaller uploads.' \
  --source-file correction-source.json \
  --python "$protect_python" \
  --timeout 60 \
  --output ./verified-upload-limit
```

Expected: JSON with `"status": "verified"`, exit code `0`, and a new
`verified-upload-limit/` bundle. Read its report and inspect the exported
test. Both runs use identical test bytes against committed application code.
To rerun the verifier, choose a new output directory.

The test remains an ordinary pytest test. You can run the local copy without
Alluvia:

```bash
"$protect_python" -m pytest -q test_upload_policy.py::test_upload_limit_is_exclusive
```

This result demonstrates one boundary check, not complete upload validation.
The verifier runs test code with your user permissions; its temporary
snapshots are not a security sandbox. See the [full guide](../../PROTECT.md)
for source attribution, other outcomes, and supported project layouts.
