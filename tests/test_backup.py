import sqlite3

from mockup_tool.storage.backup import snapshot


def test_snapshot_copies_db_and_keeps_latest(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert snapshot("t") is None  # chưa có DB thì bỏ qua

    with sqlite3.connect(tmp_path / "mockup.db") as db:
        db.execute("CREATE TABLE x (v INTEGER)")
        db.execute("INSERT INTO x VALUES (42)")

    (tmp_path / "backups").mkdir()
    for stamp in ("20200101-000000", "20200102-000000"):
        (tmp_path / "backups" / f"t-{stamp}.db").write_bytes(b"")

    path = snapshot("t", keep=2)
    with sqlite3.connect(path) as copy:
        assert copy.execute("SELECT v FROM x").fetchone() == (42,)
    assert sorted(p.name for p in (tmp_path / "backups").glob("t-*.db")) == ["t-20200102-000000.db", path.name]
