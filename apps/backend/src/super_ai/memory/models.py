"""SQLAlchemy ORM models for backend memory persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Base metadata for memory ORM models."""


class UserModel(Base):
    """Persisted authenticated user."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class AuthSessionModel(Base):
    """Persisted revocable auth session."""

    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BackgroundJobModel(Base):
    """Durable owner-scoped background work item with a renewable lease.

    监控链路第 2 层：durable job runtime 的持久化状态。
    status/attempt/max_attempts/available_at 控制调度与重试；
    lease_owner/lease_expires_at 防止多个 worker 重复认领；
    cancel_requested_at 支持协作式取消，系统任务以 ``system`` 作为 owner。
    """

    __tablename__ = "background_jobs"
    __table_args__ = (
        Index("ix_background_jobs_status_available", "status", "available_at"),
        Index("ix_background_jobs_owner_created", "owner_user_id", "created_at"),
        Index("ix_background_jobs_resource", "owner_user_id", "resource_type", "resource_id"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=900)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retry_of_job_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BackgroundJobEventModel(Base):
    """Durable ordered event emitted by a background job.

    事件在同一个 job 内按单调 sequence 排序，唯一约束避免重复写入。
    SSE 从 sequence 0 回放，因此事件必须落库而不是只存在于进程内存。
    job_id 级联删除；owner_user_id 用于查询时按用户过滤。
    """

    __tablename__ = "background_job_events"
    __table_args__ = (
        UniqueConstraint("job_id", "sequence", name="uq_background_job_events_sequence"),
        Index("ix_background_job_events_owner_job_sequence", "owner_user_id", "job_id", "sequence"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("background_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UserFeedbackModel(Base):
    """Owner-scoped feedback for a supported product artifact."""

    __tablename__ = "user_feedback"
    __table_args__ = (
        UniqueConstraint(
            "owner_user_id",
            "target_type",
            "target_id",
            "subject_key",
            name="uq_user_feedback_target",
        ),
        Index("ix_user_feedback_owner_target", "owner_user_id", "target_type", "target_id"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[str] = mapped_column(String(160), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    rating: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    correction: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class McpConnectionModel(Base):
    """Owner-scoped MCP server connection configuration."""

    __tablename__ = "mcp_connections"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "name", name="uq_mcp_connections_owner_name"),
        Index("ix_mcp_connections_owner_updated", "owner_user_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    transport: Mapped[str] = mapped_column(String(40), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    retries: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_check_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_tool_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_tools: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PrometheusSourceModel(Base):
    """Owner-scoped Prometheus data source configuration."""

    __tablename__ = "prometheus_sources"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "name", name="uq_prometheus_sources_owner_name"),
        Index("ix_prometheus_sources_owner_updated", "owner_user_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    username: Mapped[str | None] = mapped_column(String(240), nullable=True)
    password: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    max_series: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    last_check_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KnowledgeDocumentModel(Base):
    """Persisted knowledge base document metadata."""

    __tablename__ = "knowledge_documents"
    __table_args__ = (
        Index(
            "ix_knowledge_documents_owner_kb_uploaded_at",
            "owner_user_id",
            "knowledge_base_id",
            "uploaded_at",
        ),
        Index(
            "ix_knowledge_documents_owner_kb_hash",
            "owner_user_id",
            "knowledge_base_id",
            "content_hash",
        ),
        Index(
            "ix_knowledge_documents_owner_kb_document",
            "owner_user_id",
            "knowledge_base_id",
            "id",
        ),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    knowledge_base_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(160), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    index_status: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DocumentIndexTaskModel(Base):
    """Persisted document indexing task attempt."""

    __tablename__ = "document_index_tasks"
    __table_args__ = (
        Index(
            "ix_document_index_tasks_owner_document_created_at",
            "owner_user_id",
            "knowledge_base_id",
            "document_id",
            "created_at",
        ),
        Index("ix_document_index_tasks_owner_status", "owner_user_id", "status"),
        Index("ix_document_index_tasks_retry_of", "retry_of_task_id"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    knowledge_base_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_of_task_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ChatSessionModel(Base):
    """Persisted chat session."""

    __tablename__ = "chat_sessions"
    __table_args__ = (Index("ix_chat_sessions_owner_updated_at", "owner_user_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(240), nullable=True)
    memory_mode: Mapped[str] = mapped_column(String(40), nullable=False, default="every_30_turns")
    memory_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    compacted_message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    context_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_compacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class UserChatConfigurationModel(Base):
    """Persisted owner-scoped chat assembly selection."""

    __tablename__ = "user_chat_configurations"

    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    system_prompt_id: Mapped[str] = mapped_column(String(120), nullable=False)
    skill_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class UserChatPromptModel(Base):
    """Persisted owner-scoped editable system prompt."""

    __tablename__ = "user_chat_prompts"
    __table_args__ = (
        Index("ix_user_chat_prompts_owner_updated_at", "owner_user_id", "updated_at"),
        Index("ix_user_chat_prompts_owner_default", "owner_user_id", "is_default"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_default: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class UserChatSkillModel(Base):
    """Persisted owner-scoped uploaded Skill markdown file."""

    __tablename__ = "user_chat_skills"
    __table_args__ = (
        Index("ix_user_chat_skills_owner_updated_at", "owner_user_id", "updated_at"),
        Index("ix_user_chat_skills_owner_filename", "owner_user_id", "filename"),
        UniqueConstraint("owner_user_id", "name", name="uq_user_chat_skills_owner_name"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(240), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(1024), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ChatMessageModel(Base):
    """Persisted chat message."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_session_created_at", "session_id", "created_at"),
        Index(
            "ix_chat_messages_owner_session_created_at",
            "owner_user_id",
            "session_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class AgentToolCallAuditModel(Base):
    """Persisted tenant-scoped Agent tool invocation audit entry.

    CheckConstraint 保证 chat_session 与 diagnostic_task 两个父资源二选一。
    arguments 与 result_summary 必须已脱敏/截断，错误信息不得包含凭据。
    owner_user_id 与父资源 id 共同用于鉴权查询与生命周期级联。
    """

    __tablename__ = "tool_call_audits"
    __table_args__ = (
        CheckConstraint(
            "(chat_session_id IS NOT NULL AND diagnostic_task_id IS NULL) OR "
            "(chat_session_id IS NULL AND diagnostic_task_id IS NOT NULL)",
            name="ck_tool_call_audits_one_parent",
        ),
        Index(
            "ix_tool_call_audits_owner_session_created_at",
            "owner_user_id",
            "chat_session_id",
            "created_at",
        ),
        Index(
            "ix_tool_call_audits_owner_diagnostic_created_at",
            "owner_user_id",
            "diagnostic_task_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    chat_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    diagnostic_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("aiops_diagnostic_tasks.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class DiagnosticTaskModel(Base):
    """Persisted AIOps diagnostic task.

    状态机：accepted → running → succeeded / failed / cancelled。
    input_payload 保存 query/alert/scope；result_payload 保存最终诊断与报告 id。
    owner_user_id + created_at 索引支撑“我的诊断历史”分页与自动诊断去重。
    """

    __tablename__ = "aiops_diagnostic_tasks"
    __table_args__ = (
        Index("ix_aiops_diagnostic_tasks_created_at", "created_at"),
        Index("ix_aiops_diagnostic_tasks_owner_created_at", "owner_user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DiagnosticReportModel(Base):
    """Persisted diagnostic report.

    一条诊断任务可以有多份报告（当前实现通常一份）。
    payload 保存结构化诊断、evidenceIds、llmUsage 与 citationValidation。
    task_id 级联删除；所有读取都必须带 owner_user_id。
    """

    __tablename__ = "aiops_diagnostic_reports"
    __table_args__ = (
        Index("ix_aiops_diagnostic_reports_task_created_at", "task_id", "created_at"),
        Index(
            "ix_aiops_diagnostic_reports_owner_task_created_at",
            "owner_user_id",
            "task_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("aiops_diagnostic_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class DiagnosticCaseModel(Base):
    """Structured owner-scoped knowledge case created from a successful diagnosis.

    监控链路的下游消费者：由人工确认的成功诊断沉淀为可复用案例。
    owner_user_id + service 索引支撑“按服务检索相似案例”。
    案例不参与诊断执行，也不反向修改原始证据。
    """

    __tablename__ = "aiops_diagnostic_cases"
    __table_args__ = (
        Index("ix_aiops_diagnostic_cases_owner_created_at", "owner_user_id", "created_at"),
        Index("ix_aiops_diagnostic_cases_owner_service", "owner_user_id", "service"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("aiops_diagnostic_tasks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    report_id: Mapped[str] = mapped_column(
        ForeignKey("aiops_diagnostic_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    index_task_id: Mapped[str] = mapped_column(
        ForeignKey("document_index_tasks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    alert_name: Mapped[str] = mapped_column(String(240), nullable=False)
    service: Mapped[str] = mapped_column(String(240), nullable=False)
    keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    root_cause: Mapped[str] = mapped_column(Text, nullable=False)
    remediation: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    confirmed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class DiagnosticStepModel(Base):
    """Ordered plan and execution stage for an AIOps diagnostic.

    phase 取值 planner / executor / replanner / report。
    sequence 由调用方在串行持久化时按“已存步骤数 + 1”分配。
    payload 保存该阶段的输入/输出快照，用于证据链回放。
    """

    __tablename__ = "aiops_diagnostic_steps"
    __table_args__ = (
        Index(
            "ix_aiops_diagnostic_steps_owner_task_sequence",
            "owner_user_id",
            "task_id",
            "sequence",
        ),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("aiops_diagnostic_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class DiagnosticEvidenceModel(Base):
    """Typed, immutable evidence produced by an AIOps diagnostic.

    kind 区分 log / metric / knowledge_reference；source 记录产生它的工具名。
    step_id 与 tool_call_id 可选地指向步骤和审计，step 删除时置空而非级联。
    payload 保存已脱敏的 arguments 与 output；报告引用只能指向这些已保存记录。
    """

    __tablename__ = "aiops_diagnostic_evidence"
    __table_args__ = (
        Index(
            "ix_aiops_diagnostic_evidence_owner_task_created_at",
            "owner_user_id",
            "task_id",
            "created_at",
        ),
        Index(
            "ix_aiops_diagnostic_evidence_owner_task_kind",
            "owner_user_id",
            "task_id",
            "kind",
        ),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("aiops_diagnostic_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_id: Mapped[str | None] = mapped_column(
        ForeignKey("aiops_diagnostic_steps.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    tool_call_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str] = mapped_column(String(240), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class ReportEvidenceLinkModel(Base):
    """Owner-scoped provenance edge from a diagnostic report to evidence.

    一条链接表示某份报告引用了某条证据；调用方对 evidence_ids 去重后写入。
    report_id / evidence_id 均级联删除，避免留下悬空溯源边。
    owner_user_id + task_id 冗余存储，便于按用户直接鉴权与清理。
    """

    __tablename__ = "aiops_report_evidence_links"
    __table_args__ = (
        Index(
            "ix_aiops_report_evidence_links_owner_report",
            "owner_user_id",
            "report_id",
        ),
        Index(
            "ix_aiops_report_evidence_links_owner_task_evidence",
            "owner_user_id",
            "task_id",
            "evidence_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("aiops_diagnostic_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    report_id: Mapped[str] = mapped_column(
        ForeignKey("aiops_diagnostic_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("aiops_diagnostic_evidence.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class ToolCallAuditModel(Base):
    """Persisted tool call audit entry for a diagnostic task.

    与通用 tool_call_audits 不同，本表只服务诊断任务并带 task_id。
    status 从 started 收敛到 completed / failed，完成后补齐 completed_at。
    result_payload 与 error_message 必须已脱敏/截断，不得记录凭据或原始输出全文。
    """

    __tablename__ = "aiops_tool_call_audits"
    __table_args__ = (
        Index("ix_aiops_tool_call_audits_task_created_at", "task_id", "created_at"),
        Index(
            "ix_aiops_tool_call_audits_owner_task_created_at",
            "owner_user_id",
            "task_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("aiops_diagnostic_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class GraphCheckpointModel(Base):
    """Persisted LangGraph checkpoint for a diagnostic task.

    每个图节点执行后保存一次 payload 快照，用于证据链与问题排查。
    thread_id 固定为 aiops:{task_id}，checkpoint_ns 记录节点名。
    (thread_id, checkpoint_ns, checkpoint_id) 索引支撑按图身份读取。
    """

    __tablename__ = "aiops_graph_checkpoints"
    __table_args__ = (
        Index("ix_aiops_graph_checkpoints_task_thread", "task_id", "thread_id"),
        Index(
            "ix_aiops_graph_checkpoints_owner_task_thread",
            "owner_user_id",
            "task_id",
            "thread_id",
        ),
        Index(
            "ix_aiops_graph_checkpoints_identity",
            "thread_id",
            "checkpoint_ns",
            "checkpoint_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("aiops_diagnostic_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    thread_id: Mapped[str] = mapped_column(String(160), nullable=False)
    checkpoint_ns: Mapped[str] = mapped_column(String(160), nullable=False)
    checkpoint_id: Mapped[str] = mapped_column(String(160), nullable=False)
    checkpoint_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class ActiveAlertModel(Base):
    """Latest normalized active-alert snapshot refreshed by the recurring poll job.

    Alert state is infrastructure-level and shared, not user-attributed business data;
    the snapshot is therefore global rather than ``owner_user_id`` scoped, matching the
    ``GET /aiops/alerts/active`` behavior.

    链路位置：_alert_poll_job_handler 成功后整表原子替换。
    id 是告警稳定指纹，便于订阅端做差量展示。
    接口只对已认证用户开放，但数据本身不按用户过滤。
    """

    __tablename__ = "active_alerts"
    __table_args__ = (
        Index("ix_active_alerts_revision", "revision"),
        Index("ix_active_alerts_recorded_at", "recorded_at"),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(240), nullable=False)
    alert_name: Mapped[str] = mapped_column(String(240), nullable=False)
    service: Mapped[str] = mapped_column(String(240), nullable=False)
    severity: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    starts_at: Mapped[str] = mapped_column(String(80), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    labels: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    annotations: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ActiveAlertSnapshotMetaModel(Base):
    """Durable monotonic revision counter for the global alert snapshot.

    Stored separately from alert rows so an empty snapshot still carries a
    monotonic revision for SSE change detection.

    空快照也必须 +1，否则前端无法感知“告警已被清空”。
    SSE 只在 revision 变化时推送，因此更新必须单调且与快照替换同事务。
    """

    __tablename__ = "active_alert_snapshot_meta"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
