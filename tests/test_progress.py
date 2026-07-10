"""Issue #4: progress reporting primitives. Engine/CLI wiring is tested in
test_engine_progress.py; here we pin the reporter behaviors themselves."""
import io

from alluvia.progress import NullReporter, PlainReporter, RichReporter, make_reporter


def test_null_reporter_is_silent_and_safe():
    r = NullReporter()
    r.start("distilling", total=10)
    r.advance()
    r.note("anything")
    r.finish()
    r.close()                                    # nothing raised, nothing output


def test_plain_reporter_small_total_prints_every_item():
    buf = io.StringIO()
    r = PlainReporter(buf)
    r.start("distilling", total=3)
    for _ in range(3):
        r.advance()
    r.finish()
    out = buf.getvalue()
    assert "distilling" in out and "3 " in out.splitlines()[0]
    assert "1/3" in out and "2/3" in out and "3/3" in out


def test_plain_reporter_large_total_prints_deciles_only():
    buf = io.StringIO()
    r = PlainReporter(buf)
    r.start("distilling", total=100)
    for _ in range(100):
        r.advance()
    counts = [l for l in buf.getvalue().splitlines() if "/100" in l]
    assert len(counts) == 10                     # 10,20,…,100 — not 100 lines
    assert "100/100" in counts[-1]


def test_plain_reporter_unknown_total_prints_every_25():
    buf = io.StringIO()
    r = PlainReporter(buf)
    r.start("ingesting", total=None)
    for _ in range(60):
        r.advance()
    r.finish()
    out = buf.getvalue()
    assert "25" in out and "50" in out
    assert "60" in out                           # finish reports the final count


def test_plain_reporter_notes_are_prefixed_lines():
    buf = io.StringIO()
    r = PlainReporter(buf)
    r.start("mapping themes", total=2)
    r.note("rate-limited: waiting 30s (llama-3.3-70b-versatile)")
    assert "waiting 30s" in buf.getvalue()


def test_make_reporter_plain_when_stream_is_not_a_tty():
    assert isinstance(make_reporter(io.StringIO()), PlainReporter)


def test_rich_reporter_smoke():
    """rich ships via typer — construct and drive it without a terminal."""
    r = RichReporter()
    r.start("distilling", total=2)
    r.advance()
    r.note("waiting 5s")
    r.start("embedding", total=None)
    r.advance()
    r.finish()
    r.close()
