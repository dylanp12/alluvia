import json
import os
import sqlite3
from alluvia.ingest.vscode_fork import VSCodeForkAdapter, FLAVORS


def _mk_db(path, item_rows=(), disk_rows=()):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value BLOB)")
    for k, v in item_rows:
        conn.execute("INSERT INTO ItemTable VALUES (?,?)", (k, v))
    if disk_rows:
        conn.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value BLOB)")
        for k, v in disk_rows:
            conn.execute("INSERT INTO cursorDiskKV VALUES (?,?)", (k, v))
    conn.commit()
    conn.close()


def _cursor_chatdata(tab_id="tab-1"):
    # real shape observed via scripts/probe_forks.py (workspace ItemTable)
    return json.dumps({"tabs": [{
        "tabId": tab_id,
        "chatTitle": "Understanding rate limits",
        "bubbles": [
            {"type": "user", "text": "how do I rate limit the api",
             "createdAt": 1767225600000},
            {"type": "ai", "text": "use a token bucket per key",
             "createdAt": 1767225660000},
        ],
    }]})


def _root(tmp_path, app="Cursor", ws_dbs=None, global_item=(), global_disk=()):
    root = tmp_path / app
    for name, rows in (ws_dbs or {}).items():
        _mk_db(str(root / "User" / "workspaceStorage" / name / "state.vscdb"),
               item_rows=rows)
    if global_item or global_disk:
        _mk_db(str(root / "User" / "globalStorage" / "state.vscdb"),
               item_rows=global_item, disk_rows=global_disk)
    return str(root)


def test_cursor_workspace_chatdata_tabs(tmp_path):
    root = _root(tmp_path, ws_dbs={
        "ws1": [("workbench.panel.aichat.view.aichat.chatdata",
                 _cursor_chatdata("tab-A"))]})
    sessions = list(VSCodeForkAdapter("cursor", root=root).read())
    assert len(sessions) == 1
    s = sessions[0]
    assert s.source == "cursor" and s.id == "cursor:tab-A"
    assert s.title.startswith("Understanding rate limits")
    assert [m.role for m in s.messages] == ["user", "assistant"]
    assert s.started_at is not None                      # ms-epoch parsed


def test_cursor_global_composer_inline_and_bubble_join(tmp_path):
    # real shapes observed via probe: composerData with inline conversation,
    # composerData headers-only joined to bubbleId:{composerId}:{uuid}, and empty.
    disk = [
        ("composerData:comp-inline", json.dumps({
            "composerId": "comp-inline", "name": "Retry policy design",
            "createdAt": 1767225600000, "lastUpdatedAt": 1767225700000,
            "conversation": [
                {"type": 1, "text": "design the retry policy"},
                {"type": 2, "text": "exponential backoff with jitter"},
            ]})),
        ("composerData:comp-hdrs", json.dumps({
            "composerId": "comp-hdrs", "name": "WSL installation fixes",
            "createdAt": 1767312000000,
            "conversation": [],
            "fullConversationHeadersOnly": [
                {"bubbleId": "b1", "type": 1},
                {"bubbleId": "b2", "type": 2},
            ]})),
        ("bubbleId:comp-hdrs:b1", json.dumps({"bubbleId": "b1", "type": 1,
                                              "text": "wsl install is broken"})),
        ("bubbleId:comp-hdrs:b2", json.dumps({"bubbleId": "b2", "type": 2,
                                              "text": "reset the wsl vhd"})),
        ("composerData:comp-empty", json.dumps({
            "composerId": "comp-empty", "conversation": [],
            "fullConversationHeadersOnly": []})),
    ]
    root = _root(tmp_path, global_disk=disk)
    sessions = {s.native_id: s for s in VSCodeForkAdapter("cursor", root=root).read()}
    assert set(sessions) == {"comp-inline", "comp-hdrs"}    # empty composer skipped
    assert sessions["comp-inline"].title.startswith("Retry policy design")
    assert [m.role for m in sessions["comp-inline"].messages] == ["user", "assistant"]
    assert sessions["comp-inline"].started_at is not None
    joined = sessions["comp-hdrs"]
    assert [m.text for m in joined.messages] == ["wsl install is broken",
                                                 "reset the wsl vhd"]
    assert [m.role for m in joined.messages] == ["user", "assistant"]


def test_per_db_failure_is_isolated(tmp_path):
    root = _root(tmp_path, ws_dbs={
        "good": [("workbench.panel.aichat.view.aichat.chatdata", _cursor_chatdata())]})
    bad = tmp_path / "Cursor" / "User" / "workspaceStorage" / "bad" / "state.vscdb"
    os.makedirs(bad.parent, exist_ok=True)
    bad.write_bytes(b"this is not sqlite")
    sessions = list(VSCodeForkAdapter("cursor", root=str(root)).read())
    assert len(sessions) == 1                            # good DB still ingested


def test_non_matching_keys_and_bad_json_are_skipped(tmp_path):
    root = _root(tmp_path, ws_dbs={"ws1": [
        ("workbench.colorTheme", json.dumps("dark")),                 # irrelevant key
        ("workbench.panel.aichat.view.aichat.chatdata", "{not json"),  # bad payload
    ]})
    assert list(VSCodeForkAdapter("cursor", root=str(root)).read()) == []


def test_missing_root_yields_nothing(tmp_path):
    assert list(VSCodeForkAdapter("cursor", root=str(tmp_path / "nope")).read()) == []


def test_flavors_registry_has_all_three():
    assert set(FLAVORS) == {"cursor", "windsurf", "antigravity"}


# ---- Task 3: Windsurf / Antigravity — observed reality is UI-state-only ----

def test_windsurf_real_ui_state_ships_log_and_skip(tmp_path, caplog):
    # keys observed by the probe: UI state + an EMPTY session index
    root = _root(tmp_path, app="Windsurf", ws_dbs={"w1": [
        ("windsurf.cascadeViewContainerId.state", json.dumps({"visible": True})),
        ("chat.ChatSessionStore.index", json.dumps({"version": 1, "entries": {}})),
    ]})
    with caplog.at_level("INFO"):
        sessions = list(VSCodeForkAdapter("windsurf", root=root).read())
    assert sessions == []
    assert any("no chat sessions found" in r.message for r in caplog.records)


def test_antigravity_real_ui_state_ships_log_and_skip(tmp_path, caplog):
    root = _root(tmp_path, app="Antigravity", ws_dbs={"a1": [
        ("antigravity.agentViewContainerId.state", json.dumps({"visible": True})),
        ("chat.ChatSessionStore.index", json.dumps({"version": 1, "entries": {}})),
    ]})
    with caplog.at_level("INFO"):
        sessions = list(VSCodeForkAdapter("antigravity", root=root).read())
    assert sessions == []
    assert any("no chat sessions found" in r.message for r in caplog.records)


def test_generic_machinery_extracts_if_a_fork_ever_stores_json_chat(tmp_path):
    # forward-path test: if a future Windsurf version stores a JSON conversation
    # under a cascade-ish key, the generic shapes pick it up with no new code.
    root = _root(tmp_path, app="Windsurf", ws_dbs={"w1": [
        ("windsurf.cascadeChatSessions", json.dumps({
            "id": "cascade-1",
            "conversation": [
                {"role": "user", "text": "profile the slow query",
                 "timestamp": 1767312000000},
                {"role": "assistant", "text": "add an index on user_id"},
            ]})),
    ]})
    sessions = list(VSCodeForkAdapter("windsurf", root=root).read())
    assert len(sessions) == 1
    assert sessions[0].source == "windsurf" and sessions[0].native_id == "cascade-1"
    assert [m.role for m in sessions[0].messages] == ["user", "assistant"]
