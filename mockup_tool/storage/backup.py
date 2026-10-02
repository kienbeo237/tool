"""Bản sao SQLite an toàn khi app đang ghi (API backup của sqlite3, không copy thẳng file).

    python -m mockup_tool.storage.backup [nhãn] [số bản giữ lại]

Ghi vào UPLOAD_DIR/backups/<nhãn>-<thời điểm>.db, chỉ giữ `keep` bản mới nhất của cùng nhãn.
"""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from mockup_tool.config import load_settings

_SQLITE_PREFIX = "sqlite:///"


def snapshot(label: str = "manual", keep: int = 7) -> Path | None:
    settings = load_settings()
    if not settings.database_url.startswith(_SQLITE_PREFIX):
        return None  # Postgres: dùng pg_dump
    db = Path(settings.database_url.removeprefix(_SQLITE_PREFIX))
    if not db.exists():
        return None

    dest_dir = settings.upload_dir / "backups"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{label}-{datetime.now():%Y%m%d-%H%M%S}.db"
    src, dst = sqlite3.connect(db), sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    for old in sorted(dest_dir.glob(f"{label}-*.db"))[:-keep]:
        old.unlink()
    return dest


if __name__ == "__main__":
    path = snapshot(sys.argv[1] if len(sys.argv) > 1 else "manual", int(sys.argv[2]) if len(sys.argv) > 2 else 7)
    print(f"backup: {path}" if path else "backup: bỏ qua (chưa có DB SQLite)")
