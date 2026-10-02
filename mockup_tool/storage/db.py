"""Database: SQLite (mặc định) hoặc Postgres qua DATABASE_URL. Chỉ chứa dữ liệu người dùng
và các phiên bản quy tắc; ảnh nằm trên đĩa, DB giữ đường dẫn tương đối."""

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class RuleVersion(Base):
    __tablename__ = "rule_versions"
    __table_args__ = (UniqueConstraint("category", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict] = mapped_column(JSON)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Request(Base):
    __tablename__ = "requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    product_type: Mapped[str] = mapped_column(String(64))
    fields: Mapped[dict] = mapped_column(JSON)  # phần riêng của danh mục, vd {garment_color, placement, thread_colors}
    aspect_ratio: Mapped[str] = mapped_column(String(16))
    background_mode: Mapped[str] = mapped_column(String(16))  # preset | saved | custom
    background_key: Mapped[str | None] = mapped_column(String(64))  # khoá preset hoặc id reference
    scene_json: Mapped[dict] = mapped_column(JSON)  # bối cảnh đã giải (sau ưu tiên)
    scene_overrides: Mapped[dict | None] = mapped_column(JSON)
    custom_note: Mapped[str] = mapped_column(Text, default="")
    idea_images: Mapped[list] = mapped_column(JSON, default=list)
    style_images: Mapped[list] = mapped_column(JSON, default=list)
    design_json: Mapped[dict | None] = mapped_column(JSON)
    rendered_prompt: Mapped[str] = mapped_column(Text, default="")  # bản code dựng
    prompt_text: Mapped[str] = mapped_column(Text, default="")  # bản cuối (có thể đã sửa tay)
    text_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    source_request_id: Mapped[int | None] = mapped_column(ForeignKey("requests.id"))
    rules_version: Mapped[int] = mapped_column(Integer)
    model_name: Mapped[str] = mapped_column(String(64), default="")
    used_example_ids: Mapped[list] = mapped_column(JSON, default=list)
    model_raw: Mapped[list] = mapped_column(JSON, default=list)  # output thô của model, để debug
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok | approved | error
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class ApprovedExample(Base):
    __tablename__ = "approved_examples"
    __table_args__ = (Index("ix_examples_lookup", "category", "is_canonical", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"))
    category: Mapped[str] = mapped_column(String(64))
    product_type: Mapped[str] = mapped_column(String(64))
    placement: Mapped[str] = mapped_column(String(64), default="")
    garment_color: Mapped[str] = mapped_column(String(64), default="")
    background_key: Mapped[str | None] = mapped_column(String(64))
    design_json: Mapped[dict] = mapped_column(JSON)
    design_text: Mapped[str] = mapped_column(Text)  # đoạn thiết kế đã render (đoạn 3 với áo thêu)
    prompt_text: Mapped[str] = mapped_column(Text)
    is_canonical: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(Text, default="")
    rules_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ReferenceAsset(Base):
    """Ảnh nền (scene) và ảnh style. Ảnh scene Custom được cache ở đây ngay cả khi chưa
    bấm Lưu (saved=False), để cùng một ảnh không phải gọi vision lần hai."""

    __tablename__ = "reference_assets"
    __table_args__ = (UniqueConstraint("sha256", "kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))  # scene | style
    image_path: Mapped[str] = mapped_column(Text)
    description: Mapped[dict | None] = mapped_column(JSON)
    label: Mapped[str] = mapped_column(String(200), default="")
    saved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Generation(Base):
    __tablename__ = "generations"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"), index=True)
    image_path: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))  # ok | error
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


def make_session_factory(database_url: str) -> sessionmaker:
    engine = create_engine(database_url)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(conn, _):
            cur = conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)
