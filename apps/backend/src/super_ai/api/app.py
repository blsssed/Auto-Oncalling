"""FastAPI 应用工厂；监控链路的入口和返回口都在这里。

阅读顺序：create_app → 健康检查路由 → create_aiops_diagnostic
→ aiops_job_handler → stream_aiops_diagnostic 内的 event_stream。
每个路由只看三件事：参数从哪来、调用哪个 service、返回什么信封。
第一次读请跳过：认证、聊天、知识库、MCP CRUD、文件上传相关路由。

不变量：
- 路由函数不写 docstring：FastAPI 会把它暴露成 OpenAPI description；
- 诊断请求只入队，真正的执行在 BackgroundJobRuntime 的 worker 里；
- owner 只取自认证上下文，不接受客户端传来的 owner 作为授权依据。

【学习路线 · 监控链路 第 0 站「请求进入」】
上一站：无（链路起点）→ 本站：create_app → create_aiops_diagnostic
（POST /aiops/diagnostics，只入队）→ stream_aiops_diagnostic（SSE 回放）
→ 下一站：jobs/runtime.py 的 BackgroundJobRuntime。
学习重点：请求怎样变成已认证用户（_current_user）与统一信封
（success_response，定义在 api/responses.py）；成功/失败两种信封各长什么样。
自检：为什么诊断请求只入队就返回 taskId？答不出再回读 create_aiops_diagnostic。
"""
# pyright: reportUnusedFunction=false

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path, PurePosixPath
from time import monotonic
from typing import Annotated, Literal, Protocol, cast
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from super_ai.aiops import AiopsDiagnosticService, DiagnosisCasePersistor
from super_ai.aiops.auto_diagnosis import (
    AutoDiagnosisSettings,
    auto_diagnosis_input_payload,
    auto_diagnosis_query,
    load_auto_diagnosis_settings,
)
from super_ai.aiops.investigation import DiagnosticScope, redact
from super_ai.alerts import (
    ActiveAlert,
    ActiveAlertProvider,
    AlertProviderError,
    build_alertmanager_alert_provider,
)
from super_ai.auth.repositories import AuthRepository, UserRecord
from super_ai.auth.service import AuthError, AuthResult, AuthService
from super_ai.auth.sqlite import SQLiteAuthRepository
from super_ai.chat import (
    ChatAgentRunner,
    ChatStreamingService,
    LangChainChatAgentRunner,
    encode_sse,
)
from super_ai.chat.configuration import (
    DEFAULT_CHAT_PROMPT_CONTENT,
    DEFAULT_CHAT_PROMPT_LABEL,
    validate_chat_prompt_content,
    validate_skill_upload,
)
from super_ai.chat.memory import (
    SUPPORTED_CHAT_MEMORY_MODES,
    ChatContextLimitReached,
    ChatMemoryService,
    memory_payload,
)
from super_ai.documents import (
    ALLOWED_DOCUMENT_EXTENSIONS,
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DOCUMENT_MAX_SIZE_BYTES,
    MARKDOWN_DOCUMENT_MIME_TYPES,
    PDF_DOCUMENT_MIME_TYPES,
    TEXT_DOCUMENT_EXTENSIONS,
    ChunkingSettings,
    DocumentIndexingService,
    chunk_document_text,
    extract_indexable_text,
    load_chunking_settings,
)
from super_ai.error_catalog import ERROR_DEFINITIONS
from super_ai.feedback import FeedbackError, UserFeedbackService
from super_ai.foundation import get_foundation_info
from super_ai.jobs import BackgroundJobContext, BackgroundJobRuntime, JobCancelled
from super_ai.llm import (
    EmbeddingModel,
    LlmProvider,
    RerankModel,
    build_default_llm_provider,
    load_llm_provider_config,
)
from super_ai.llm.config_writer import (
    ApiKeyRequiredError,
    LlmConfigApplyError,
    LlmConfigUpdate,
    LlmConfigView,
    UserConfigInvalidError,
    apply_llm_config_update,
    load_llm_config_view,
)
from super_ai.log_store import build_log_store
from super_ai.mcp_client import LocalMcpClient
from super_ai.mcp_connections import McpConnectionError, McpConnectionService
from super_ai.memory.database import (
    create_memory_engine,
    create_memory_session_factory,
    load_memory_database_settings,
)
from super_ai.memory.repositories import (
    ActiveAlertRecord,
    ActiveAlertRepository,
    AgentToolCallAuditRecord,
    BackgroundJobRecord,
    BackgroundJobRepository,
    ChatMessageRecord,
    ChatSessionRecord,
    DiagnosticCaseRecord,
    DiagnosticEvidenceRecord,
    DiagnosticReportRecord,
    DiagnosticStepRecord,
    DiagnosticTaskRecord,
    DocumentIndexTaskRecord,
    GraphCheckpointRecord,
    KnowledgeDocumentRecord,
    McpConnectionRecord,
    MemoryRepositories,
    PrometheusSourceRecord,
    ReportEvidenceLinkRecord,
    TimeRangeFilter,
    UserChatConfigurationRecord,
    UserChatConfigurationRepository,
    UserChatPromptRecord,
    UserChatPromptRepository,
    UserChatSkillRecord,
    UserChatSkillRepository,
    UserFeedbackRecord,
)
from super_ai.memory.sqlite import create_sqlite_memory_repositories
from super_ai.metrics import MetricQueryError, MetricSeries, PromqlProvider, build_promql_provider
from super_ai.observability import (
    configure_structured_logging,
    elapsed_ms,
    emit_event,
    reset_request_id,
    set_request_id,
)
from super_ai.project_config import (
    ProjectConfigurationError,
    project_config_section,
    required_int,
    required_str,
)
from super_ai.prometheus_sources import PrometheusSourceError, PrometheusSourceService
from super_ai.retrieval import (
    KnowledgeRetrievalTool,
    RetrievalCache,
    RetrievalVectorStore,
    build_retrieval_cache,
)
from super_ai.tracing import (
    TracingCallbackProvider,
    build_tracing_provider,
    load_tracing_settings,
)
from super_ai.vector_store import (
    MilvusHealthCheckResult,
    VectorChunkRecord,
    build_default_milvus_vector_store,
    load_milvus_vector_store_settings,
)

from .observability import RequestMetrics
from .responses import ApiErrorException, error_response, success_response

bearer_scheme = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)
BearerCredentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


class RegisterRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    email: str
    display_name: str = Field(alias="displayName")
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class UpdateProfileRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    display_name: str = Field(alias="displayName", min_length=1, max_length=160)


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    current_password: str = Field(alias="currentPassword", min_length=1, max_length=512)
    new_password: str = Field(alias="newPassword", min_length=8, max_length=512)


class UpdateLlmConfigurationRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    api_key: str | None = Field(default=None, alias="apiKey", max_length=512)
    base_url: str = Field(alias="baseUrl", min_length=1, max_length=512)
    chat_model: str = Field(alias="chatModel", min_length=1, max_length=128)
    context_window_tokens: int = Field(alias="contextWindowTokens", ge=1)
    embedding_model: str = Field(alias="embeddingModel", min_length=1, max_length=128)
    embedding_dimensions: int = Field(alias="embeddingDimensions", ge=1)
    rerank_model: str = Field(alias="rerankModel", min_length=1, max_length=128)
    rerank_url: str = Field(alias="rerankUrl", min_length=1, max_length=512)
    temperature: float = Field(ge=0, le=2)
    timeout_seconds: float = Field(alias="timeoutSeconds", ge=1, le=600)
    max_retries: int = Field(alias="maxRetries", ge=1)
    langfuse_enabled: bool | None = Field(default=None, alias="langfuseEnabled")
    langfuse_host: str | None = Field(default=None, alias="langfuseHost", max_length=512)
    langfuse_public_key: str | None = Field(default=None, alias="langfusePublicKey", max_length=512)
    langfuse_secret_key: str | None = Field(default=None, alias="langfuseSecretKey", max_length=512)


class CreateChatSessionRequest(BaseModel):
    title: str | None = None


class AppendChatMessageRequest(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    metadata: dict[str, object] = Field(default_factory=dict)


class StreamChatMessageRequest(BaseModel):
    content: str
    metadata: dict[str, object] = Field(default_factory=dict)


class UpdateChatMemoryRequest(BaseModel):
    mode: Literal["every_30_turns", "context_70_percent", "manual"]


class UpdateChatAssemblyConfigurationRequest(BaseModel):
    system_prompt_id: str = Field(alias="systemPromptId")
    skill_ids: list[str] = Field(alias="skillIds")


class CreateChatPromptRequest(BaseModel):
    label: str
    content: str


class UpdateChatPromptRequest(BaseModel):
    label: str
    content: str


class CreateAiopsDiagnosticRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8000)
    alert: dict[str, object] = Field(default_factory=dict)
    scope: DiagnosticScope | None = None


class ConfirmDiagnosticCaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    confirmed: Literal[True]
    root_cause: str = Field(alias="rootCause", min_length=1, max_length=4000)
    remediation: str = Field(min_length=1, max_length=4000)


class UpsertFeedbackRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    target_type: Literal["chat_message", "citation", "diagnostic_step", "diagnostic_report"] = (
        Field(alias="targetType")
    )
    target_id: str = Field(alias="targetId", min_length=1, max_length=160)
    subject_id: str | None = Field(default=None, alias="subjectId", max_length=160)
    rating: Literal["positive", "negative"]
    reason: str | None = Field(default=None, max_length=80)
    comment: str | None = Field(default=None, max_length=2000)
    correction: str | None = Field(default=None, max_length=4000)


class McpConnectionMutationRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=120)
    transport: Literal["sse", "streamable_http"]
    url: str = Field(min_length=1, max_length=2048)
    enabled: bool = True
    timeout_seconds: int = Field(default=15, alias="timeoutSeconds", ge=1, le=300)
    retries: int = Field(default=1, ge=0, le=5)


class PrometheusSourceMutationRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=1, max_length=2048, alias="baseUrl")
    username: str | None = Field(default=None, max_length=240)
    password: str | None = Field(default=None, max_length=512)
    enabled: bool = True
    timeout_seconds: int = Field(default=10, alias="timeoutSeconds", ge=1, le=300)
    max_series: int = Field(default=20, alias="maxSeries", ge=1, le=100)


class PrometheusInstantQueryRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_id: str = Field(min_length=1, max_length=80, alias="sourceId")
    query: str = Field(min_length=1, max_length=4000)
    time_ms: int | None = Field(default=None, alias="timeMs")


class PrometheusRangeQueryRequestModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_id: str = Field(min_length=1, max_length=80, alias="sourceId")
    query: str = Field(min_length=1, max_length=4000)
    start_ms: int = Field(alias="startMs")
    end_ms: int = Field(alias="endMs")
    step_seconds: int = Field(alias="stepSeconds", ge=5, le=300)


class AiopsDiagnosticRunner(Protocol):
    def stream(
        self,
        *,
        task: DiagnosticTaskRecord,
        accessible_knowledge_base_ids: Sequence[str],
    ) -> AsyncIterator[dict[str, object]]:
        """Stream one persisted AIOps diagnostic execution."""
        ...


class MilvusHealthCheckProvider(Protocol):
    def health_check(self) -> MilvusHealthCheckResult:
        """Return Milvus readiness/config status."""
        ...


class DocumentVectorStoreProvider(MilvusHealthCheckProvider, Protocol):
    def initialize(self) -> None:
        """Ensure vector collection/indexes exist before document writes."""
        ...

    def delete_document_chunks(
        self,
        *,
        tenant_id: str,
        knowledge_base_id: str,
        document_id: str,
    ) -> None:
        """Delete Milvus chunks for a scoped document."""
        ...

    def insert_chunks(self, chunks: Sequence[VectorChunkRecord]) -> None:
        """Insert Milvus chunks for document indexing."""
        ...


class DocumentIndexTaskScheduler(Protocol):
    def schedule(self, *, owner_user_id: str, task_id: str) -> Awaitable[None] | None:
        """Schedule a persisted index task without blocking the request."""
        ...


class DurableDocumentIndexTaskScheduler:
    """Enqueue document indexing in the durable background runtime."""

    def __init__(self, app: FastAPI) -> None:
        self._app = app

    async def schedule(self, *, owner_user_id: str, task_id: str) -> None:
        repository = _background_job_repository_from_app(self._app)
        existing = await repository.find_for_resource(
            owner_user_id=owner_user_id,
            resource_type="document_index_task",
            resource_id=task_id,
        )
        if existing is None:
            await repository.enqueue(
                owner_user_id=owner_user_id,
                job_id=f"job_{uuid4().hex}",
                kind="document_index",
                resource_type="document_index_task",
                resource_id=task_id,
                payload={"taskId": task_id},
                max_attempts=3,
                timeout_seconds=900,
            )
        await _background_job_runtime_from_app(self._app).start()


def create_app(
    *,
    database_url: str | None = None,
    project_config_path: str | Path | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    vector_store: MilvusHealthCheckProvider | None = None,
    embedding_model: EmbeddingModel | None = None,
    rerank_model: RerankModel | None = None,
    llm_provider: LlmProvider | None = None,
    chat_agent_runner: ChatAgentRunner | None = None,
    aiops_diagnostic_runner: AiopsDiagnosticRunner | None = None,
    alert_provider: ActiveAlertProvider | None = None,
    index_task_scheduler: DocumentIndexTaskScheduler | None = None,
) -> FastAPI:
    """Create the backend API application."""
    resolved_project_config_path = (
        str(project_config_path) if project_config_path is not None else None
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
        # 先启动任务 runtime，再确保全局告警轮询存在；顺序不能颠倒。
        runtime = cast(BackgroundJobRuntime, application.state.background_job_runtime)
        await runtime.start()
        await _ensure_alert_poll(application)
        try:
            yield
        finally:
            # 先停 worker 再释放连接池，避免后台任务继续使用已关闭的连接。
            await runtime.stop()
            owned_engine = cast(AsyncEngine | None, application.state.memory_engine)
            if owned_engine is not None:
                await owned_engine.dispose()

    configure_structured_logging()
    app = FastAPI(title="Super AI API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    engine: AsyncEngine | None = None
    if session_factory is None:
        engine = create_memory_engine(database_url, config_path=resolved_project_config_path)
        session_factory = create_memory_session_factory(engine)
    app.state.project_config_path = resolved_project_config_path
    app.state.memory_engine = engine
    app.state.memory_session_factory = session_factory
    auth_repository = SQLiteAuthRepository(session_factory)
    app.state.auth_repository = auth_repository
    app.state.auth_service = AuthService(auth_repository)
    repositories = create_sqlite_memory_repositories(session_factory)
    app.state.memory_repositories = repositories
    app.state.vector_store = vector_store or build_default_milvus_vector_store(
        config_path=resolved_project_config_path
    )
    app.state.embedding_model = embedding_model
    app.state.rerank_model = rerank_model
    app.state.llm_provider = llm_provider
    app.state.chat_agent_runner = chat_agent_runner
    app.state.aiops_diagnostic_runner = aiops_diagnostic_runner
    app.state.alert_provider = alert_provider
    # 记录哪些 provider 是测试注入的：配置热生效时绝不能覆盖注入的 fake。
    app.state.injected_providers = {
        "embedding_model": embedding_model is not None,
        "rerank_model": rerank_model is not None,
        "llm_provider": llm_provider is not None,
        "chat_agent_runner": chat_agent_runner is not None,
        "aiops_diagnostic_runner": aiops_diagnostic_runner is not None,
    }
    if repositories.background_jobs is None:
        raise RuntimeError("Background job repository is required.")
    background_runtime = BackgroundJobRuntime(repositories.background_jobs)
    background_runtime.register("document_index", _document_index_job_handler(app))
    background_runtime.register("aiops_diagnosis", aiops_job_handler(app))
    background_runtime.register("alert_poll", _alert_poll_job_handler(app))
    app.state.background_job_runtime = background_runtime
    app.state.index_task_scheduler = index_task_scheduler or DurableDocumentIndexTaskScheduler(app)
    app.state.request_metrics = RequestMetrics()

    @app.middleware("http")
    async def observe_request(request: Request, call_next: RequestResponseEndpoint) -> Response:
        # request id 优先复用上游传入值，便于跨服务串联；缺失时本地生成。
        request_id = request.headers.get("x-request-id") or f"req_{uuid4().hex}"
        request.state.request_id = request_id
        # ContextVar 让后续日志/事件自动带上 requestId，必须在 finally 中重置。
        correlation_token = set_request_id(request_id)
        started_at = monotonic()
        response: Response | None = None
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception as exc:
            # 只记录异常类型，避免把可能含敏感数据的原始异常消息写入日志。
            emit_event(logger, "request.error", errorCategory=exc.__class__.__name__)
            raise
        finally:
            # 未产生响应时按 500 计失败；指标与完成事件在 finally 中始终记录。
            status_code = response.status_code if response is not None else 500
            latency_ms = elapsed_ms(started_at)
            app.state.request_metrics.record(latency_ms=latency_ms, status_code=status_code)
            emit_event(
                logger,
                "request.complete",
                method=request.method,
                path=request.url.path,
                status=status_code,
                latencyMs=latency_ms,
            )
            reset_request_id(correlation_token)

    @app.exception_handler(ApiErrorException)
    async def handle_api_error(request: Request, exc: ApiErrorException) -> object:
        # 业务错误只记录错误码；响应沿用统一 envelope 与错误目录文案。
        emit_event(logger, "request.error", errorCode=exc.code)
        return error_response(request, exc.code, message=exc.message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, _exc: RequestValidationError) -> object:
        # 校验失败不记录请求体，统一返回 VALIDATION_INVALID_ARGUMENT。
        emit_event(logger, "request.error", errorCode="VALIDATION_INVALID_ARGUMENT")
        return error_response(request, "VALIDATION_INVALID_ARGUMENT")

    @app.get("/health")
    async def health(request: Request) -> object:
        # 只反映进程自身信息，不探测数据库/Milvus/LLM，保证探针不被外部依赖拖垮。
        foundation = get_foundation_info()
        return success_response(
            request,
            {
                "service": foundation.service,
                "status": foundation.status,
                "version": foundation.version,
            },
        )

    @app.get("/metrics")
    async def metrics(request: Request) -> object:
        # 进程内指标：重启清零、多进程各自独立；这里只暴露请求数与平均延迟。
        snapshot = request.app.state.request_metrics.snapshot()
        average = (
            snapshot.total_latency_ms / snapshot.request_count if snapshot.request_count else 0.0
        )
        return success_response(
            request,
            {
                "requestCount": snapshot.request_count,
                "failureCount": snapshot.failure_count,
                "averageLatencyMs": round(average, 3),
            },
        )

    @app.get("/health/mcp")
    async def mcp_health(request: Request) -> object:
        # MCP 未就绪返回 503，便于负载均衡与运维直接判断依赖状态。
        result = await _mcp_client(request).readiness()
        return success_response(request, result, status_code=200 if result["ok"] else 503)

    @app.get("/ready")
    async def ready(request: Request) -> object:
        # 四项依赖全部 ok 才返回 200；任一失败返回 503，但 body 仍给出明细。
        dependencies = await _runtime_dependency_payload(request)
        is_ready = all(bool(component["ok"]) for component in dependencies.values())
        return success_response(
            request,
            {"status": "ready" if is_ready else "degraded", "dependencies": dependencies},
            status_code=200 if is_ready else 503,
        )

    @app.get("/config/check")
    async def config_check(request: Request) -> object:
        # 配置合法性（valid）与运行时依赖（ok）分开判断，便于区分配置问题与依赖问题。
        configuration = _configuration_check_payload(request)
        dependencies = await _runtime_dependency_payload(request)
        is_valid = all(bool(component["valid"]) for component in configuration.values())
        is_ready = all(bool(component["ok"]) for component in dependencies.values())
        return success_response(
            request,
            {
                "status": "ready" if is_valid and is_ready else "degraded",
                "configuration": configuration,
                "dependencies": dependencies,
            },
            status_code=200 if is_valid and is_ready else 503,
        )

    @app.get("/config/llm")
    async def get_llm_configuration(
        request: Request,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        # 掩码视图：只返回 apiKeyConfigured/apiKeyLast4，绝不回传密钥本体。
        try:
            view = load_llm_config_view(request.app.state.project_config_path)
        except ProjectConfigurationError as exc:
            raise ApiErrorException("BUSINESS_CONFLICT") from exc
        return success_response(request, _llm_config_view_payload(view))

    @app.put("/config/llm")
    async def update_llm_configuration(
        request: Request,
        body: UpdateLlmConfigurationRequest,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        update = LlmConfigUpdate(
            api_key=body.api_key,
            base_url=body.base_url.strip(),
            chat_model=body.chat_model.strip(),
            context_window_tokens=body.context_window_tokens,
            embedding_model=body.embedding_model.strip(),
            embedding_dimensions=body.embedding_dimensions,
            rerank_model=body.rerank_model.strip(),
            rerank_url=body.rerank_url.strip(),
            temperature=body.temperature,
            timeout_seconds=body.timeout_seconds,
            max_retries=body.max_retries,
            langfuse_enabled=body.langfuse_enabled,
            langfuse_host=body.langfuse_host,
            langfuse_public_key=body.langfuse_public_key,
            langfuse_secret_key=body.langfuse_secret_key,
        )
        try:
            view = apply_llm_config_update(request.app.state.project_config_path, update)
        except ApiKeyRequiredError as exc:
            raise ApiErrorException("VALIDATION_MISSING_FIELD", str(exc)) from exc
        except UserConfigInvalidError as exc:
            raise ApiErrorException("BUSINESS_CONFLICT") from exc
        except ProjectConfigurationError as exc:
            raise ApiErrorException("BUSINESS_CONFLICT") from exc
        except LlmConfigApplyError as exc:
            raise ApiErrorException("MODEL_CONFIGURATION_INVALID") from exc
        # 写盘成功后让运行时缓存失效，下一个请求即用新配置重建 provider。
        _invalidate_llm_runtime_cache(request.app)
        return success_response(request, _llm_config_view_payload(view))

    @app.post("/auth/register")
    async def register(request: Request, body: RegisterRequest) -> object:
        service = _auth_service(request)
        try:
            result = await service.register(
                email=body.email,
                display_name=body.display_name,
                password=body.password,
            )
        except AuthError as exc:
            raise _api_error(exc) from exc
        return success_response(request, _auth_result_payload(result), status_code=201)

    @app.post("/auth/login")
    async def login(request: Request, body: LoginRequest) -> object:
        service = _auth_service(request)
        try:
            result = await service.login(email=body.email, password=body.password)
        except AuthError as exc:
            raise _api_error(exc) from exc
        return success_response(request, _auth_result_payload(result))

    @app.post("/auth/logout")
    async def logout(
        request: Request,
        credentials: BearerCredentials,
    ) -> object:
        token = _bearer_token(credentials)
        try:
            await _auth_service(request).logout(token)
        except AuthError as exc:
            raise _api_error(exc) from exc
        return success_response(request, {"revoked": True})

    @app.get("/auth/me")
    async def current_user(
        request: Request,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        return success_response(request, _user_payload(user))

    @app.put("/auth/profile")
    async def update_profile(
        request: Request,
        body: UpdateProfileRequest,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        try:
            updated = await _auth_service(request).update_profile(
                user_id=user.id,
                display_name=body.display_name,
            )
        except AuthError as exc:
            raise _api_error(exc) from exc
        return success_response(request, _user_payload(updated))

    @app.put("/auth/password")
    async def change_password(
        request: Request,
        body: ChangePasswordRequest,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        # 改密码成功会吊销该用户全部会话（含当前），前端需引导重新登录。
        try:
            await _auth_service(request).change_password(
                user_id=user.id,
                current_password=body.current_password,
                new_password=body.new_password,
            )
        except AuthError as exc:
            raise _api_error(exc) from exc
        return success_response(request, {"changed": True})

    @app.get("/background-jobs")
    async def list_background_jobs(
        request: Request,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        jobs = await _background_job_repository(request).list(owner_user_id=user.id)
        return success_response(request, {"items": [_background_job_payload(job) for job in jobs]})

    @app.get("/background-jobs/{job_id}")
    async def get_background_job(
        request: Request,
        job_id: str,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        job = await _background_job_repository(request).get(
            owner_user_id=user.id,
            job_id=job_id,
        )
        if job is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        return success_response(request, _background_job_payload(job))

    @app.post("/background-jobs/{job_id}:cancel")
    async def cancel_background_job(
        request: Request,
        job_id: str,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        job = await _background_job_repository(request).request_cancel(
            owner_user_id=user.id,
            job_id=job_id,
        )
        if job is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        await _cancel_background_resource(request, job)
        return success_response(request, _background_job_payload(job))

    @app.post("/background-jobs/{job_id}:retry")
    async def retry_background_job(
        request: Request,
        job_id: str,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        job = await _background_job_repository(request).retry(
            owner_user_id=user.id,
            source_job_id=job_id,
            new_job_id=f"job_{uuid4().hex}",
        )
        if job is None:
            raise ApiErrorException("BUSINESS_CONFLICT")
        await _background_job_runtime(request).start()
        return success_response(request, _background_job_payload(job), status_code=202)

    @app.get("/feedback")
    async def list_feedback(
        request: Request,
        user: Annotated[UserRecord, Depends(_current_user)],
        target_type: Annotated[str, Query(alias="targetType")],
        target_id: Annotated[str, Query(alias="targetId")],
    ) -> object:
        try:
            feedback = await _feedback_service(request).list_for_target(
                owner_user_id=user.id,
                target_type=target_type,
                target_id=target_id,
            )
        except FeedbackError as exc:
            raise ApiErrorException(exc.code, exc.message) from exc
        return success_response(
            request,
            {"items": [_user_feedback_payload(item) for item in feedback]},
        )

    @app.post("/feedback")
    async def upsert_feedback(
        request: Request,
        body: UpsertFeedbackRequest,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        try:
            feedback = await _feedback_service(request).upsert(
                owner_user_id=user.id,
                target_type=body.target_type,
                target_id=body.target_id,
                subject_id=body.subject_id,
                rating=body.rating,
                reason=body.reason,
                comment=body.comment,
                correction=body.correction,
            )
        except FeedbackError as exc:
            raise ApiErrorException(exc.code, exc.message) from exc
        return success_response(request, _user_feedback_payload(feedback))

    @app.delete("/feedback/{feedback_id}")
    async def delete_feedback(
        request: Request,
        feedback_id: str,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        try:
            deleted = await _feedback_service(request).delete(
                owner_user_id=user.id,
                feedback_id=feedback_id,
            )
        except FeedbackError as exc:
            raise ApiErrorException(exc.code, exc.message) from exc
        if not deleted:
            raise ApiErrorException("AUTH_FORBIDDEN")
        return success_response(request, {"deleted": True, "feedbackId": feedback_id})

    @app.get("/mcp/connections")
    async def list_mcp_connections(
        request: Request,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        records = await _mcp_connection_service(request).list(owner_user_id=user.id)
        return success_response(
            request,
            {"items": [_mcp_connection_payload(record) for record in records]},
        )

    @app.post("/mcp/connections")
    async def create_mcp_connection(
        request: Request,
        body: McpConnectionMutationRequest,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        try:
            record = await _mcp_connection_service(request).create(
                owner_user_id=user.id,
                **body.model_dump(),
            )
        except McpConnectionError as exc:
            raise ApiErrorException(exc.code, exc.message) from exc
        return success_response(request, _mcp_connection_payload(record), status_code=201)

    @app.put("/mcp/connections/{connection_id}")
    async def update_mcp_connection(
        request: Request,
        connection_id: str,
        body: McpConnectionMutationRequest,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        try:
            record = await _mcp_connection_service(request).update(
                owner_user_id=user.id,
                connection_id=connection_id,
                **body.model_dump(),
            )
        except McpConnectionError as exc:
            raise ApiErrorException(exc.code, exc.message) from exc
        return success_response(request, _mcp_connection_payload(record))

    @app.delete("/mcp/connections/{connection_id}")
    async def delete_mcp_connection(
        request: Request,
        connection_id: str,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        deleted = await _mcp_connection_service(request).delete(
            owner_user_id=user.id,
            connection_id=connection_id,
        )
        if not deleted:
            raise ApiErrorException("AUTH_FORBIDDEN")
        return success_response(request, {"deleted": True, "connectionId": connection_id})

    @app.post("/mcp/connections/{connection_id}:check")
    async def check_mcp_connection(
        request: Request,
        connection_id: str,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        try:
            record, tools = await _mcp_connection_service(request).check(
                owner_user_id=user.id,
                connection_id=connection_id,
            )
        except McpConnectionError as exc:
            raise ApiErrorException(exc.code, exc.message) from exc
        return success_response(
            request,
            {
                "connection": _mcp_connection_payload(record),
                "tools": [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "inputSchema": tool.input_schema,
                        "serverName": tool.server_name,
                    }
                    for tool in tools
                ],
            },
        )

    @app.get("/prometheus/sources")
    async def list_prometheus_sources(
        request: Request,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        records = await _prometheus_source_service(request).list(owner_user_id=user.id)
        return success_response(
            request,
            {"items": [_prometheus_source_payload(record) for record in records]},
        )

    @app.post("/prometheus/sources")
    async def create_prometheus_source(
        request: Request,
        body: PrometheusSourceMutationRequest,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        try:
            record = await _prometheus_source_service(request).create(
                owner_user_id=user.id,
                **body.model_dump(),
            )
        except PrometheusSourceError as exc:
            raise ApiErrorException(exc.code, exc.message) from exc
        return success_response(request, _prometheus_source_payload(record), status_code=201)

    @app.put("/prometheus/sources/{source_id}")
    async def update_prometheus_source(
        request: Request,
        source_id: str,
        body: PrometheusSourceMutationRequest,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        try:
            record = await _prometheus_source_service(request).update(
                owner_user_id=user.id,
                source_id=source_id,
                **body.model_dump(),
            )
        except PrometheusSourceError as exc:
            raise ApiErrorException(exc.code, exc.message) from exc
        return success_response(request, _prometheus_source_payload(record))

    @app.delete("/prometheus/sources/{source_id}")
    async def delete_prometheus_source(
        request: Request,
        source_id: str,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        deleted = await _prometheus_source_service(request).delete(
            owner_user_id=user.id,
            source_id=source_id,
        )
        if not deleted:
            raise ApiErrorException("AUTH_FORBIDDEN")
        return success_response(request, {"deleted": True, "sourceId": source_id})

    @app.post("/prometheus/sources/{source_id}:check")
    async def check_prometheus_source(
        request: Request,
        source_id: str,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        try:
            record = await _prometheus_source_service(request).check(
                owner_user_id=user.id,
                source_id=source_id,
            )
        except PrometheusSourceError as exc:
            raise ApiErrorException(exc.code, exc.message) from exc
        return success_response(
            request,
            {
                "source": _prometheus_source_payload(record),
                "check": {
                    "ok": record.last_check_ok,
                    "error": record.last_error,
                    "checkedAt": (
                        record.last_checked_at.isoformat() if record.last_checked_at else None
                    ),
                },
            },
        )

    @app.get("/prometheus/labels/{label}/values")
    async def list_prometheus_label_values(
        request: Request,
        label: str,
        user: Annotated[UserRecord, Depends(_current_user)],
        source_id: Annotated[str, Query(alias="sourceId", min_length=1, max_length=80)],
    ) -> object:
        try:
            _record, values = await _prometheus_source_service(request).label_values(
                owner_user_id=user.id,
                source_id=source_id,
                label=label,
            )
        except PrometheusSourceError as exc:
            raise ApiErrorException(exc.code, exc.message) from exc
        return success_response(request, {"label": label, "values": values})

    @app.post("/prometheus/query")
    async def run_prometheus_instant_query(
        request: Request,
        body: PrometheusInstantQueryRequest,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        at_seconds = body.time_ms / 1000 if body.time_ms is not None else None
        try:
            _record, series = await _prometheus_source_service(request).query_instant(
                owner_user_id=user.id,
                source_id=body.source_id,
                query=body.query,
                at_seconds=at_seconds,
            )
        except PrometheusSourceError as exc:
            raise ApiErrorException(exc.code, exc.message) from exc
        return success_response(request, _prometheus_query_payload(body.query, series))

    @app.post("/prometheus/query-range")
    async def run_prometheus_range_query(
        request: Request,
        body: PrometheusRangeQueryRequestModel,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        try:
            _record, series = await _prometheus_source_service(request).query_range(
                owner_user_id=user.id,
                source_id=body.source_id,
                query=body.query,
                start_seconds=body.start_ms / 1000,
                end_seconds=body.end_ms / 1000,
                step_seconds=body.step_seconds,
            )
        except PrometheusSourceError as exc:
            raise ApiErrorException(exc.code, exc.message) from exc
        payload = _prometheus_query_payload(body.query, series)
        payload["startMs"] = body.start_ms
        payload["endMs"] = body.end_ms
        payload["stepSeconds"] = body.step_seconds
        return success_response(request, payload)

    @app.get("/knowledge-bases")
    async def list_knowledge_bases(
        request: Request,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        return success_response(
            request,
            {
                "items": [
                    {
                        "id": f"kb_{user.id}",
                        "name": "Personal knowledge base",
                        "ownerUserId": user.id,
                    }
                ]
            },
        )

    @app.get("/knowledge-bases/{knowledge_base_id}/documents")
    async def list_knowledge_documents(
        request: Request,
        knowledge_base_id: str,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        _ensure_knowledge_base_access(user, knowledge_base_id)
        documents = await _memory_repositories(request).documents.list_documents(
            owner_user_id=user.id,
            knowledge_base_id=knowledge_base_id,
        )
        return success_response(
            request,
            {"items": [_knowledge_document_payload(document) for document in documents]},
        )

    @app.post("/knowledge-bases/{knowledge_base_id}/documents")
    async def upload_knowledge_document(
        request: Request,
        knowledge_base_id: str,
        user: Annotated[UserRecord, Depends(_current_user)],
        file: Annotated[UploadFile, File()],
        overwrite: Annotated[bool, Form()] = False,
        chunking: Annotated[str, Form()] = "",
    ) -> object:
        _ensure_knowledge_base_access(user, knowledge_base_id)
        content = await file.read()
        try:
            _validate_upload(file, content)
            try:
                indexable_text = extract_indexable_text(file.filename or "document", content)
            except ValueError as exc:
                raise ApiErrorException("VALIDATION_INVALID_ARGUMENT", str(exc)) from exc
            chunking_configuration = _parse_chunking_configuration(chunking)
            content_hash = f"sha256:{sha256(content).hexdigest()}"
            repositories = _memory_repositories(request)
            duplicate = await repositories.documents.find_active_by_hash(
                owner_user_id=user.id,
                knowledge_base_id=knowledge_base_id,
                content_hash=content_hash,
            )
            if duplicate is not None and not overwrite:
                raise ApiErrorException("BUSINESS_CONFLICT")
            if duplicate is not None:
                _delete_document_vectors(
                    request,
                    tenant_id=user.id,
                    knowledge_base_id=knowledge_base_id,
                    document_id=duplicate.id,
                )
                await repositories.documents.mark_document_deleted(
                    owner_user_id=user.id,
                    knowledge_base_id=knowledge_base_id,
                    document_id=duplicate.id,
                )
            document = await repositories.documents.create_document(
                owner_user_id=user.id,
                document_id=f"doc_{uuid4().hex}",
                knowledge_base_id=knowledge_base_id,
                filename=file.filename or "document",
                size_bytes=len(content),
                mime_type=file.content_type or "application/octet-stream",
                content_hash=content_hash,
                metadata={
                    "upload": "user-selected",
                    "indexableText": indexable_text,
                    "chunking": chunking_configuration,
                },
            )
        finally:
            await file.close()
        return success_response(
            request,
            {
                "document": _knowledge_document_payload(document),
                "duplicateOfDocumentId": duplicate.id if duplicate is not None else None,
                "overwrite": overwrite,
            },
            status_code=201,
        )

    @app.get("/knowledge-bases/{knowledge_base_id}/documents/{document_id}")
    async def get_knowledge_document(
        request: Request,
        knowledge_base_id: str,
        document_id: str,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        _ensure_knowledge_base_access(user, knowledge_base_id)
        document = await _memory_repositories(request).documents.get_document(
            owner_user_id=user.id,
            knowledge_base_id=knowledge_base_id,
            document_id=document_id,
        )
        if document is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        return success_response(request, _knowledge_document_payload(document))

    @app.get("/knowledge-bases/{knowledge_base_id}/documents/{document_id}/chunk-preview")
    async def get_document_chunk_preview(
        request: Request,
        knowledge_base_id: str,
        document_id: str,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        _ensure_knowledge_base_access(user, knowledge_base_id)
        document = await _memory_repositories(request).documents.get_document(
            owner_user_id=user.id, knowledge_base_id=knowledge_base_id, document_id=document_id
        )
        if document is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        configuration = _document_chunking_payload(document)
        chunks = chunk_document_text(
            _decode_indexable_document(document),
            strategy=cast(str, configuration["strategy"]),
            chunk_size=_runtime_chunk_size(configuration),
            chunk_overlap=_runtime_chunk_overlap(configuration),
        )
        return success_response(
            request,
            {
                "preview": {
                    "configuration": configuration,
                    "totalChunks": len(chunks),
                    "truncated": len(chunks) > 12,
                    "items": [
                        {
                            "index": item.index,
                            "characterCount": len(item.content),
                            "excerpt": item.content[:400],
                            **({"headingPath": item.heading_path} if item.heading_path else {}),
                        }
                        for item in chunks[:12]
                    ],
                }
            },
        )

    @app.delete("/knowledge-bases/{knowledge_base_id}/documents/{document_id}")
    async def delete_knowledge_document(
        request: Request,
        knowledge_base_id: str,
        document_id: str,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        _ensure_knowledge_base_access(user, knowledge_base_id)
        repositories = _memory_repositories(request)
        document = await repositories.documents.get_document(
            owner_user_id=user.id,
            knowledge_base_id=knowledge_base_id,
            document_id=document_id,
        )
        if document is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        _delete_document_vectors(
            request,
            tenant_id=user.id,
            knowledge_base_id=knowledge_base_id,
            document_id=document.id,
        )
        deleted = await repositories.documents.mark_document_deleted(
            owner_user_id=user.id,
            knowledge_base_id=knowledge_base_id,
            document_id=document.id,
        )
        if deleted is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        return success_response(request, {"deleted": True, "documentId": document.id})

    @app.post("/knowledge-bases/{knowledge_base_id}/documents/{document_id}/index-tasks")
    async def create_document_index_task(
        request: Request,
        knowledge_base_id: str,
        document_id: str,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        _ensure_knowledge_base_access(user, knowledge_base_id)
        document = await _memory_repositories(request).documents.get_document(
            owner_user_id=user.id,
            knowledge_base_id=knowledge_base_id,
            document_id=document_id,
        )
        if document is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        task = await _memory_repositories(request).document_index_tasks.create_task(
            owner_user_id=user.id,
            task_id=f"index_task_{uuid4().hex}",
            knowledge_base_id=knowledge_base_id,
            document_id=document_id,
            status="pending",
        )
        await _schedule_index_task(request, owner_user_id=user.id, task_id=task.id)
        return success_response(
            request,
            {"task": _document_index_task_payload(task), "scheduled": True},
            status_code=202,
        )

    @app.get("/knowledge-bases/{knowledge_base_id}/documents/{document_id}/index-tasks/{task_id}")
    async def get_document_index_task(
        request: Request,
        knowledge_base_id: str,
        document_id: str,
        task_id: str,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        _ensure_knowledge_base_access(user, knowledge_base_id)
        task = await _memory_repositories(request).document_index_tasks.get_task(
            owner_user_id=user.id,
            task_id=task_id,
        )
        if (
            task is None
            or task.knowledge_base_id != knowledge_base_id
            or task.document_id != document_id
        ):
            raise ApiErrorException("AUTH_FORBIDDEN")
        return success_response(request, _document_index_task_payload(task))

    @app.post(
        "/knowledge-bases/{knowledge_base_id}/documents/{document_id}/index-tasks/{task_id}:retry"
    )
    async def retry_document_index_task(
        request: Request,
        knowledge_base_id: str,
        document_id: str,
        task_id: str,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        _ensure_knowledge_base_access(user, knowledge_base_id)
        previous = await _memory_repositories(request).document_index_tasks.get_task(
            owner_user_id=user.id,
            task_id=task_id,
        )
        if (
            previous is None
            or previous.knowledge_base_id != knowledge_base_id
            or previous.document_id != document_id
        ):
            raise ApiErrorException("AUTH_FORBIDDEN")
        if previous.status != "failed":
            raise ApiErrorException("BUSINESS_CONFLICT")
        task = await _memory_repositories(request).document_index_tasks.create_retry(
            owner_user_id=user.id,
            task_id=f"index_task_{uuid4().hex}",
            retry_of_task_id=previous.id,
        )
        await _schedule_index_task(request, owner_user_id=user.id, task_id=task.id)
        return success_response(
            request,
            {
                "task": _document_index_task_payload(task),
                "retriedFromTaskId": previous.id,
                "scheduled": True,
            },
            status_code=202,
        )

    @app.post("/chat/sessions")
    async def create_chat_session(
        request: Request,
        body: CreateChatSessionRequest,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        title = _normalize_chat_title(body.title)
        repositories = _memory_repositories(request)
        session = await repositories.chat.create_session(
            owner_user_id=user.id,
            session_id=f"chat_{uuid4().hex}",
            title=title,
        )
        return success_response(
            request,
            _chat_session_payload(session, _context_window_tokens(request)),
            status_code=201,
        )

    @app.get("/chat/configuration")
    async def get_chat_configuration(
        request: Request, user: Annotated[UserRecord, Depends(_current_user)]
    ) -> object:
        prompts, skills, record = await _read_chat_configuration(request, owner_user_id=user.id)
        return success_response(request, _chat_configuration_payload(prompts, skills, record))

    @app.put("/chat/configuration")
    async def update_chat_configuration(
        request: Request,
        body: UpdateChatAssemblyConfigurationRequest,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        prompt_repository = _chat_prompt_repository(request)
        skill_repository = _chat_skill_repository(request)
        configuration_repository = _chat_configuration_repository(request)
        prompt = await prompt_repository.get(
            owner_user_id=user.id,
            prompt_id=body.system_prompt_id,
        )
        if prompt is None:
            raise ApiErrorException("VALIDATION_INVALID_ARGUMENT")
        skill_ids = list(dict.fromkeys(body.skill_ids))
        for skill_id in skill_ids:
            skill = await skill_repository.get(owner_user_id=user.id, skill_id=skill_id)
            if skill is None:
                raise ApiErrorException("VALIDATION_INVALID_ARGUMENT")
        await configuration_repository.update(
            owner_user_id=user.id,
            system_prompt_id=prompt.id,
            skill_ids=skill_ids,
        )
        prompts, skills, record = await _read_chat_configuration(request, owner_user_id=user.id)
        return success_response(request, _chat_configuration_payload(prompts, skills, record))

    @app.post("/chat/prompts")
    async def create_chat_prompt(
        request: Request,
        body: CreateChatPromptRequest,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        try:
            label, content = validate_chat_prompt_content(body.label, body.content)
        except ValueError as exc:
            raise ApiErrorException("VALIDATION_INVALID_ARGUMENT", str(exc)) from exc
        prompt = await _chat_prompt_repository(request).create(
            owner_user_id=user.id,
            prompt_id=f"prompt_{uuid4().hex}",
            label=label,
            content=content,
        )
        return success_response(request, _chat_prompt_payload(prompt), status_code=201)

    @app.put("/chat/prompts/{prompt_id}")
    async def update_chat_prompt(
        request: Request,
        prompt_id: str,
        body: UpdateChatPromptRequest,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        try:
            label, content = validate_chat_prompt_content(body.label, body.content)
        except ValueError as exc:
            raise ApiErrorException("VALIDATION_INVALID_ARGUMENT", str(exc)) from exc
        prompt = await _chat_prompt_repository(request).update(
            owner_user_id=user.id,
            prompt_id=prompt_id,
            label=label,
            content=content,
        )
        if prompt is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        return success_response(request, _chat_prompt_payload(prompt))

    @app.delete("/chat/prompts/{prompt_id}")
    async def delete_chat_prompt(
        request: Request,
        prompt_id: str,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        prompt_repository = _chat_prompt_repository(request)
        configuration_repository = _chat_configuration_repository(request)
        target = await prompt_repository.get(owner_user_id=user.id, prompt_id=prompt_id)
        if target is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        deleted = await prompt_repository.delete(owner_user_id=user.id, prompt_id=prompt_id)
        default_prompt = await prompt_repository.ensure_default(
            owner_user_id=user.id,
            label=DEFAULT_CHAT_PROMPT_LABEL,
            content=DEFAULT_CHAT_PROMPT_CONTENT,
        )
        configuration = await configuration_repository.get_or_create(
            owner_user_id=user.id,
            system_prompt_id=default_prompt.id,
            skill_ids=[],
        )
        if configuration.system_prompt_id == prompt_id:
            await configuration_repository.update(
                owner_user_id=user.id,
                system_prompt_id=default_prompt.id,
                skill_ids=configuration.skill_ids,
            )
        return success_response(request, {"promptId": prompt_id, "deleted": deleted})

    @app.post("/chat/skills")
    async def upload_chat_skill(
        request: Request,
        file: Annotated[UploadFile, File()],
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        content = await file.read()
        try:
            validated = validate_skill_upload(file.filename, content)
            skill = await _chat_skill_repository(request).create(
                owner_user_id=user.id,
                skill_id=f"skill_{uuid4().hex}",
                filename=validated.filename,
                name=validated.name,
                description=validated.description,
                content=validated.content,
                size_bytes=len(content),
            )
        except ValueError as exc:
            raise ApiErrorException("VALIDATION_INVALID_ARGUMENT", str(exc)) from exc
        return success_response(request, _chat_skill_payload(skill), status_code=201)

    @app.delete("/chat/skills/{skill_id}")
    async def delete_chat_skill(
        request: Request,
        skill_id: str,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        deleted = await _chat_skill_repository(request).delete(
            owner_user_id=user.id,
            skill_id=skill_id,
        )
        if not deleted:
            raise ApiErrorException("AUTH_FORBIDDEN")
        configuration_repository = _chat_configuration_repository(request)
        default_prompt = await _chat_prompt_repository(request).ensure_default(
            owner_user_id=user.id,
            label=DEFAULT_CHAT_PROMPT_LABEL,
            content=DEFAULT_CHAT_PROMPT_CONTENT,
        )
        configuration = await configuration_repository.get_or_create(
            owner_user_id=user.id,
            system_prompt_id=default_prompt.id,
            skill_ids=[],
        )
        skill_ids = [item for item in configuration.skill_ids if item != skill_id]
        if skill_ids != configuration.skill_ids:
            await configuration_repository.update(
                owner_user_id=user.id,
                system_prompt_id=configuration.system_prompt_id,
                skill_ids=skill_ids,
            )
        return success_response(request, {"skillId": skill_id, "deleted": True})

    @app.get("/chat/sessions")
    async def list_chat_sessions(
        request: Request,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        sessions = await _memory_repositories(request).chat.list_sessions(owner_user_id=user.id)
        return success_response(
            request,
            {
                "items": [
                    _chat_session_payload(session, _context_window_tokens(request))
                    for session in sessions
                ]
            },
        )

    @app.get("/chat/sessions/{session_id}")
    async def get_chat_session(
        request: Request,
        session_id: str,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        repositories = _memory_repositories(request)
        session = await repositories.chat.get_session(
            owner_user_id=user.id,
            session_id=session_id,
        )
        if session is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        messages = await repositories.chat.list_messages(
            owner_user_id=user.id,
            session_id=session.id,
        )
        return success_response(
            request,
            {
                "session": _chat_session_payload(session, _context_window_tokens(request)),
                "messages": [_chat_message_payload(message) for message in messages],
            },
        )

    @app.get("/chat/sessions/{session_id}/tool-call-audits")
    async def list_chat_tool_call_audits(
        request: Request,
        session_id: str,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        repositories = _memory_repositories(request)
        session = await repositories.chat.get_session(
            owner_user_id=user.id,
            session_id=session_id,
        )
        if session is None or repositories.tool_call_audits is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        audits = await repositories.tool_call_audits.list_for_chat_session(
            owner_user_id=user.id,
            chat_session_id=session.id,
        )
        return success_response(
            request,
            {"items": [_agent_tool_call_audit_payload(audit) for audit in audits]},
        )

    @app.put("/chat/sessions/{session_id}/memory")
    async def update_chat_memory(
        request: Request,
        session_id: str,
        body: UpdateChatMemoryRequest,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        if body.mode not in SUPPORTED_CHAT_MEMORY_MODES:
            raise ApiErrorException("VALIDATION_INVALID_ARGUMENT")
        repositories = _memory_repositories(request)
        session = await repositories.chat.get_session(owner_user_id=user.id, session_id=session_id)
        if session is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        history = await repositories.chat.list_messages(
            owner_user_id=user.id, session_id=session_id
        )
        service, prompt = await _chat_memory_context(request, owner_user_id=user.id)
        updated = await service.set_mode(
            owner_user_id=user.id,
            session=session,
            mode=body.mode,
            history=history,
            system_prompt=prompt,
        )
        return success_response(
            request, _chat_session_payload(updated, service.context_window_tokens)
        )

    @app.post("/chat/sessions/{session_id}/memory:compact")
    async def compact_chat_memory(
        request: Request,
        session_id: str,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        repositories = _memory_repositories(request)
        session = await repositories.chat.get_session(owner_user_id=user.id, session_id=session_id)
        if session is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        history = await repositories.chat.list_messages(
            owner_user_id=user.id, session_id=session_id
        )
        service, prompt = await _chat_memory_context(request, owner_user_id=user.id)
        updated = await service.compact(
            owner_user_id=user.id,
            session=session,
            history=history,
            system_prompt=prompt,
        )
        return success_response(
            request, _chat_session_payload(updated, service.context_window_tokens)
        )

    @app.post("/chat/sessions/{session_id}/messages")
    async def append_chat_message(
        request: Request,
        session_id: str,
        body: AppendChatMessageRequest,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        repositories = _memory_repositories(request)
        session = await repositories.chat.get_session(
            owner_user_id=user.id,
            session_id=session_id,
        )
        if session is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        if body.role == "user":
            history = await repositories.chat.list_messages(
                owner_user_id=user.id, session_id=session.id
            )
            service, prompt = await _chat_memory_context(request, owner_user_id=user.id)
            try:
                await service.prepare_message(
                    owner_user_id=user.id,
                    session=session,
                    history=history,
                    system_prompt=prompt,
                    content=body.content,
                )
            except ChatContextLimitReached as exc:
                raise ApiErrorException("CHAT_CONTEXT_LIMIT_REACHED") from exc
        message = await repositories.chat.append_message(
            owner_user_id=user.id,
            message_id=f"message_{uuid4().hex}",
            session_id=session.id,
            role=body.role,
            content=body.content,
            metadata=body.metadata,
        )
        updated_session = await _maybe_generate_chat_title(
            repositories,
            user_id=user.id,
            session=session,
            message_role=body.role,
            message_content=body.content,
        )
        return success_response(
            request,
            {
                "session": _chat_session_payload(updated_session, _context_window_tokens(request)),
                "message": _chat_message_payload(message),
            },
            status_code=201,
        )

    @app.post("/chat/sessions/{session_id}/messages:stream")
    async def stream_chat_message(
        request: Request,
        session_id: str,
        body: StreamChatMessageRequest,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> StreamingResponse:
        repositories = _memory_repositories(request)
        session = await repositories.chat.get_session(
            owner_user_id=user.id,
            session_id=session_id,
        )
        if session is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        service = ChatStreamingService(
            repositories=repositories,
            agent_runner=_chat_agent_runner(request),
            memory_service=_chat_memory_service(request),
        )

        async def event_stream() -> AsyncIterator[str]:
            async for event in service.stream_message(
                owner_user_id=user.id,
                session=session,
                content=body.content,
                metadata=body.metadata,
                accessible_knowledge_base_ids=_accessible_knowledge_base_ids(user),
            ):
                yield encode_sse(event)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    @app.post("/chat/sessions/{session_id}/messages:clear")
    async def clear_chat_messages(
        request: Request,
        session_id: str,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        repositories = _memory_repositories(request)
        session = await repositories.chat.get_session(
            owner_user_id=user.id,
            session_id=session_id,
        )
        if session is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        deleted_messages = await repositories.chat.clear_messages(
            owner_user_id=user.id,
            session_id=session.id,
        )
        return success_response(
            request,
            {
                "sessionId": session.id,
                "cleared": True,
                "deletedMessages": deleted_messages,
            },
        )

    @app.delete("/chat/sessions/{session_id}")
    async def delete_chat_session(
        request: Request,
        session_id: str,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        deleted = await _memory_repositories(request).chat.delete_session(
            owner_user_id=user.id,
            session_id=session_id,
        )
        if not deleted:
            raise ApiErrorException("AUTH_FORBIDDEN")
        return success_response(request, {"sessionId": session_id, "deleted": True})

    @app.post("/aiops/diagnostics")
    async def create_aiops_diagnostic(
        request: Request,
        body: CreateAiopsDiagnosticRequest,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        # 先落库 accepted 任务再入队；job payload 只带 diagnosticId，owner 来自认证上下文。
        task = await _memory_repositories(request).diagnostics.create_task(
            owner_user_id=user.id,
            task_id=f"diagnostic_{uuid4().hex}",
            status="accepted",
            query=body.query,
            input_payload={
                "query": body.query,
                "alert": body.alert,
                "scope": body.scope.model_dump(mode="json", by_alias=True) if body.scope else {},
            },
            result_payload={},
        )
        # 诊断任务超时 30 分钟、只尝试一次：重试会重复消耗外部查询与 LLM 成本。
        job = await _background_job_repository(request).enqueue(
            owner_user_id=user.id,
            job_id=f"job_{uuid4().hex}",
            kind="aiops_diagnosis",
            resource_type="aiops_diagnostic",
            resource_id=task.id,
            payload={"diagnosticId": task.id},
            max_attempts=1,
            timeout_seconds=1800,
        )
        await _background_job_runtime(request).start()
        payload = _diagnostic_task_payload(task)
        payload["backgroundJob"] = _background_job_payload(job)
        return success_response(
            request,
            payload,
            status_code=202,
        )

    @app.get("/aiops/alerts/active")
    async def list_active_alerts(
        request: Request,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        try:
            # 告警源失败直接 503，不能返回空列表冒充“当前无告警”。
            alerts = await _active_alert_provider(request).list_active_alerts()
        except AlertProviderError as exc:
            # 只记录失败事件，不输出 provider 响应体、URL 或凭据。
            emit_event(logger, "alerts.fetch.failed")
            raise ApiErrorException(
                "SYSTEM_UNAVAILABLE",
                "Unable to retrieve active alerts from the configured alert provider.",
            ) from exc
        # 告警本身是全局快照；诊断进度按当前用户过滤后再附加，避免泄露他人任务。
        diagnosis_entries = await _alert_diagnosis_entries_for_user(
            request.app, owner_user_id=user.id
        )
        return success_response(
            request,
            {
                "items": [
                    _active_alert_payload(alert, diagnosis_entries.get(alert.id))
                    for alert in alerts
                ]
            },
        )

    @app.get("/aiops/alerts/stream")
    async def stream_active_alerts(
        request: Request,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> StreamingResponse:
        # 惰性确保轮询任务存在，避免首次打开页面时还没有任何快照可推。
        await _ensure_alert_poll(request.app)
        repository = _active_alert_repository_from_app(request.app)

        # 闭包捕获当前用户 id，订阅期间只读取该用户的诊断进度。
        async def load_diagnosis_entries() -> dict[str, AlertDiagnosisEntry]:
            return await _alert_diagnosis_entries_for_user(
                request.app, owner_user_id=user.id
            )

        return StreamingResponse(
            alert_snapshot_stream(repository, diagnosis_loader=load_diagnosis_entries),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/aiops/diagnostics")
    async def list_aiops_diagnostics(
        request: Request,
        user: Annotated[UserRecord, Depends(_current_user)],
        start_at: Annotated[datetime | None, Query(alias="startAt")] = None,
        end_at: Annotated[datetime | None, Query(alias="endAt")] = None,
    ) -> object:
        tasks = await _memory_repositories(request).diagnostics.list_tasks(
            owner_user_id=user.id,
            time_range=TimeRangeFilter(start_at=start_at, end_at=end_at),
        )
        return success_response(
            request,
            {"items": [_diagnostic_task_payload(task) for task in reversed(tasks)]},
        )

    @app.get("/aiops/diagnostic-cases")
    async def list_aiops_diagnostic_cases(
        request: Request,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        cases = await _memory_repositories(request).diagnostics.list_cases(owner_user_id=user.id)
        return success_response(
            request,
            {"items": [_diagnostic_case_payload(case) for case in cases]},
        )

    @app.get("/aiops/diagnostic-cases/{case_id}")
    async def get_aiops_diagnostic_case(
        request: Request,
        case_id: str,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        case = await _memory_repositories(request).diagnostics.get_case(
            owner_user_id=user.id,
            case_id=case_id,
        )
        if case is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        return success_response(request, _diagnostic_case_payload(case))

    @app.get("/aiops/diagnostics/{diagnostic_id}")
    async def get_aiops_diagnostic(
        request: Request,
        diagnostic_id: str,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        task = await _memory_repositories(request).diagnostics.get_task(
            owner_user_id=user.id,
            task_id=diagnostic_id,
        )
        if task is None:
            # 不存在与不属于当前用户统一返回 AUTH_FORBIDDEN，避免泄露资源是否存在。
            raise ApiErrorException("AUTH_FORBIDDEN")
        reports = await _memory_repositories(request).diagnostics.list_reports(
            owner_user_id=user.id,
            task_id=task.id,
        )
        return success_response(request, _diagnostic_task_payload(task, reports=reports))

    @app.get("/aiops/diagnostics/{diagnostic_id}/evidence-chain")
    async def get_aiops_evidence_chain(
        request: Request,
        diagnostic_id: str,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        repositories = _memory_repositories(request)
        task = await repositories.diagnostics.get_task(
            owner_user_id=user.id,
            task_id=diagnostic_id,
        )
        if task is None:
            # 先确认任务归属，再读取步骤/证据/审计，所有查询都带 owner_user_id。
            raise ApiErrorException("AUTH_FORBIDDEN")
        # 五类数据互不依赖，并行读取以降低证据链页面的延迟。
        steps, evidence, report_links, reports, checkpoints = await asyncio.gather(
            repositories.diagnostics.list_steps(owner_user_id=user.id, task_id=task.id),
            repositories.diagnostics.list_evidence(owner_user_id=user.id, task_id=task.id),
            repositories.diagnostics.list_report_evidence_links(
                owner_user_id=user.id,
                task_id=task.id,
            ),
            repositories.diagnostics.list_reports(owner_user_id=user.id, task_id=task.id),
            repositories.diagnostics.list_checkpoints(owner_user_id=user.id, task_id=task.id),
        )
        tool_audits = []
        if repositories.tool_call_audits is not None:
            tool_audits = await repositories.tool_call_audits.list_for_diagnostic_task(
                owner_user_id=user.id,
                diagnostic_task_id=task.id,
            )
        report_evidence_ids = _report_evidence_ids(report_links)
        return success_response(
            request,
            {
                "task": _diagnostic_task_payload(task, reports=reports),
                "steps": [_diagnostic_step_payload(step) for step in steps],
                "toolCalls": [_agent_tool_call_audit_payload(audit) for audit in tool_audits],
                "evidence": [_diagnostic_evidence_payload(item) for item in evidence],
                "reports": [
                    _diagnostic_report_payload(
                        report,
                        evidence_ids=report_evidence_ids.get(report.id, []),
                    )
                    for report in reports
                ],
                "reportEvidenceLinks": [
                    _report_evidence_link_payload(link) for link in report_links
                ],
                "checkpoints": [
                    _graph_checkpoint_payload(checkpoint) for checkpoint in checkpoints
                ],
            },
        )

    @app.post("/aiops/diagnostics/{diagnostic_id}:stream")
    async def stream_aiops_diagnostic(
        request: Request,
        diagnostic_id: str,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> StreamingResponse:
        task = await _memory_repositories(request).diagnostics.get_task(
            owner_user_id=user.id,
            task_id=diagnostic_id,
        )
        if task is None:
            # 先校验任务归属，再用任务 id 定位唯一的后台 job。
            raise ApiErrorException("AUTH_FORBIDDEN")
        repository = _background_job_repository(request)
        job = await repository.find_for_resource(
            owner_user_id=user.id,
            resource_type="aiops_diagnostic",
            resource_id=task.id,
        )
        if job is None:
            raise ApiErrorException("BUSINESS_NOT_FOUND")
        # 确保 worker 已在运行，客户端才开始等待事件。
        await _background_job_runtime(request).start()

        async def event_stream() -> AsyncIterator[str]:
            # 从 sequence 0 回放持久化事件，断线重连也能补齐历史。
            sequence = 0
            error_emitted = False
            while True:
                events = await repository.list_events(
                    owner_user_id=user.id,
                    job_id=job.id,
                    after_sequence=sequence,
                )
                for stored in events:
                    sequence = stored.sequence
                    error_emitted = error_emitted or stored.payload.get("type") == "error"
                    yield encode_sse(stored.payload)
                current = await repository.get(owner_user_id=user.id, job_id=job.id)
                if current is None:
                    return
                # 终态且本轮无新事件时关闭流；failed 未发过 error 时补一条统一错误。
                if current.status in {"succeeded", "failed", "cancelled"} and not events:
                    if current.status == "failed" and not error_emitted:
                        yield encode_sse(_background_job_error_event())
                    return
                await asyncio.sleep(0.1)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    @app.post("/aiops/diagnostics/{diagnostic_id}:save-to-knowledge")
    async def save_aiops_diagnostic_case(
        request: Request,
        body: ConfirmDiagnosticCaseRequest,
        diagnostic_id: str,
        user: Annotated[UserRecord, Depends(_current_user)],
    ) -> object:
        repositories = _memory_repositories(request)
        task = await repositories.diagnostics.get_task(owner_user_id=user.id, task_id=diagnostic_id)
        if task is None or task.status not in {"succeeded", "failed"}:
            raise ApiErrorException("AUTH_FORBIDDEN")
        reports = await repositories.diagnostics.list_reports(
            owner_user_id=user.id,
            task_id=task.id,
        )
        report = reports[-1] if reports else None
        if report is None:
            raise ApiErrorException("BUSINESS_NOT_FOUND")
        if not body.root_cause.strip() or not body.remediation.strip():
            raise ApiErrorException("VALIDATION_INVALID_ARGUMENT")
        case = await DiagnosisCasePersistor(
            repositories=repositories,
            index_task_scheduler=_index_task_scheduler(request),
        ).persist(
            task=task, report=report, root_cause=body.root_cause, remediation=body.remediation
        )
        document = await repositories.documents.get_document(
            owner_user_id=user.id, knowledge_base_id=f"kb_{user.id}", document_id=case.document_id
        )
        index_task = await repositories.document_index_tasks.get_task(
            owner_user_id=user.id, task_id=case.index_task_id
        )
        if document is None or index_task is None:
            raise ApiErrorException("BUSINESS_NOT_FOUND")
        return success_response(
            request,
            {
                "document": _knowledge_document_payload(document),
                "task": _document_index_task_payload(index_task),
                "scheduled": True,
            },
            status_code=202,
        )

    return app


async def _current_user(
    request: Request,
    credentials: BearerCredentials,
) -> UserRecord:
    token = _bearer_token(credentials)
    try:
        return await _auth_service(request).authenticate_token(token)
    except AuthError as exc:
        raise _api_error(exc) from exc


def _auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


def _auth_repository_from_app(app: FastAPI) -> AuthRepository:
    return cast(AuthRepository, app.state.auth_repository)


def _memory_repositories(request: Request) -> MemoryRepositories:
    return request.app.state.memory_repositories


def _background_job_repository(request: Request) -> BackgroundJobRepository:
    return _background_job_repository_from_app(request.app)


def _background_job_repository_from_app(app: FastAPI) -> BackgroundJobRepository:
    repository = cast(MemoryRepositories, app.state.memory_repositories).background_jobs
    if repository is None:
        raise RuntimeError("Background job repository is unavailable.")
    return repository


def _background_job_runtime(request: Request) -> BackgroundJobRuntime:
    return _background_job_runtime_from_app(request.app)


def _background_job_runtime_from_app(app: FastAPI) -> BackgroundJobRuntime:
    return cast(BackgroundJobRuntime, app.state.background_job_runtime)


def _feedback_service(request: Request) -> UserFeedbackService:
    return UserFeedbackService(_memory_repositories(request))


def _mcp_connection_service(request: Request) -> McpConnectionService:
    config = project_config_section("mcp", config_path=request.app.state.project_config_path)
    return McpConnectionService(
        _memory_repositories(request),
        default_url=required_str(config, "clsSseUrl"),
        default_timeout_seconds=required_int(config, "timeoutSeconds"),
        default_retries=required_int(config, "retries"),
    )


def _prometheus_source_service(request: Request) -> PrometheusSourceService:
    """构造数据源服务；文件配置的 prometheus.baseUrl 仅用于首次播种。"""
    seed_base_url: str | None = None
    try:
        config = project_config_section(
            "prometheus", config_path=request.app.state.project_config_path
        )
        seed_base_url = required_str(config, "baseUrl")
    except ProjectConfigurationError:
        seed_base_url = None
    return PrometheusSourceService(_memory_repositories(request), seed_base_url=seed_base_url)


async def _schedule_index_task(request: Request, *, owner_user_id: str, task_id: str) -> None:
    result = _index_task_scheduler(request).schedule(
        owner_user_id=owner_user_id,
        task_id=task_id,
    )
    if inspect.isawaitable(result):
        await result


def _document_index_job_handler(
    app: FastAPI,
) -> Callable[[BackgroundJobContext], Awaitable[None]]:
    async def handle(context: BackgroundJobContext) -> None:
        await context.raise_if_cancelled()
        result = await _document_indexing_service_from_app(app).run_task(
            owner_user_id=context.job.owner_user_id,
            task_id=context.job.resource_id,
        )
        if result.status != "succeeded":
            raise RuntimeError(result.failure_reason or "Document indexing failed.")

    return handle


async def _record_diagnostic_failure(
    repositories: MemoryRepositories,
    task: DiagnosticTaskRecord,
    exc: Exception,
    *,
    failure: str,
) -> None:
    """把从未进入终态的任务补写为 failed，供 SSE 正确关闭。"""
    current = await repositories.diagnostics.get_task(
        owner_user_id=task.owner_user_id,
        task_id=task.id,
    )
    # 已经是终态的任务不覆盖，避免把 cancelled / succeeded 改成 failed。
    if current is None or current.status in {"succeeded", "cancelled", "failed"}:
        return
    await repositories.diagnostics.update_task(
        owner_user_id=task.owner_user_id,
        task_id=task.id,
        status="failed",
        result_payload={
            "failure": failure,
            "error": str(redact(str(exc)))[:500],
        },
        completed_at=datetime.now(timezone.utc),
    )


def aiops_job_handler(
    app: FastAPI,
) -> Callable[[BackgroundJobContext], Awaitable[None]]:
    """构造 aiops_diagnosis 后台任务处理器：执行诊断并逐条持久化事件。"""

    async def handle(context: BackgroundJobContext) -> None:
        repositories = cast(MemoryRepositories, app.state.memory_repositories)
        task = await repositories.diagnostics.get_task(
            owner_user_id=context.job.owner_user_id,
            task_id=context.job.resource_id,
        )
        if task is None:
            # 任务已被删除或 job 过期，直接让 runtime 记录失败。
            raise RuntimeError("Diagnostic task is unavailable.")
        try:
            runner = _aiops_diagnostic_runner(_request_for_app(app))
        except Exception as exc:
            # runner 初始化失败也要写失败终态，否则前端会一直等待 SSE。
            await _record_diagnostic_failure(
                repositories,
                task,
                exc,
                failure="Diagnostic runner could not be initialized.",
            )
            raise
        try:
            async for event in runner.stream(
                task=task,
                accessible_knowledge_base_ids=(f"kb_{context.job.owner_user_id}",),
            ):
                # 每个事件出站前都检查取消，并立即持久化供 SSE 回放。
                await context.raise_if_cancelled()
                await context.append_event(event)
        except JobCancelled:
            # 取消是协作式的：先写 cancelled 终态，再把取消异常交回 runtime。
            await repositories.diagnostics.update_task(
                owner_user_id=task.owner_user_id,
                task_id=task.id,
                status="cancelled",
                completed_at=datetime.now(timezone.utc),
            )
            raise
        updated = await repositories.diagnostics.get_task(
            owner_user_id=task.owner_user_id,
            task_id=task.id,
        )
        # runner 内部可能已把任务写成 failed；这里转成 job 失败以触发终态事件。
        if updated is None or updated.status == "failed":
            raise RuntimeError("Diagnostic execution failed.")

    return handle


_ALERT_POLL_OWNER = "system"
_ALERT_POLL_RESOURCE_TYPE = "aiops_alert_poll"
_ALERT_POLL_RESOURCE_ID = "global"
_DEFAULT_ALERT_POLL_INTERVAL_SECONDS = 10


def _active_alert_repository_from_app(app: FastAPI) -> ActiveAlertRepository:
    repository = cast(MemoryRepositories, app.state.memory_repositories).active_alerts
    if repository is None:
        raise RuntimeError("Active alert repository is unavailable.")
    return repository


def _alert_poll_interval_seconds(app: FastAPI) -> int:
    """读取告警轮询间隔；配置缺失或非法时回退到 10 秒。"""
    try:
        config = project_config_section(
            "prometheusAlerts", config_path=app.state.project_config_path
        )
    except ProjectConfigurationError:
        return _DEFAULT_ALERT_POLL_INTERVAL_SECONDS
    value = config.get("pollIntervalSeconds")
    if isinstance(value, int) and value >= 1:
        return value
    return _DEFAULT_ALERT_POLL_INTERVAL_SECONDS


async def _ensure_alert_poll(app: FastAPI) -> BackgroundJobRecord | None:
    """确保全局告警轮询链存在；已有 queued/running 周期时不重复入队。"""
    # 轮询是 system owner 的全局单例，不能按用户重复创建。
    repository = _background_job_repository_from_app(app)
    existing = await repository.find_for_resource(
        owner_user_id=_ALERT_POLL_OWNER,
        resource_type=_ALERT_POLL_RESOURCE_TYPE,
        resource_id=_ALERT_POLL_RESOURCE_ID,
    )
    if existing is not None and existing.status in {"queued", "running"}:
        return existing
    job = await repository.enqueue(
        owner_user_id=_ALERT_POLL_OWNER,
        job_id=f"job_{uuid4().hex}",
        kind="alert_poll",
        resource_type=_ALERT_POLL_RESOURCE_TYPE,
        resource_id=_ALERT_POLL_RESOURCE_ID,
        payload={},
        max_attempts=3,
        timeout_seconds=120,
        available_at=datetime.now(timezone.utc),
    )
    await _background_job_runtime_from_app(app).start()
    return job


@dataclass(frozen=True, slots=True)
class AlertDiagnosisEntry:
    """某条告警最近一次诊断的摘要，用于在告警 payload 上附加诊断状态。"""

    diagnostic_id: str
    status: str
    created_at: datetime


def _auto_diagnosis_settings(app: FastAPI) -> AutoDiagnosisSettings | None:
    """读取自动诊断配置；返回 None 表示功能关闭。"""
    return load_auto_diagnosis_settings(config_path=app.state.project_config_path)


def _alert_diagnosis_id(input_payload: Mapping[str, object]) -> str | None:
    value = input_payload.get("alertId")
    return value if isinstance(value, str) and value != "" else None


def _alert_diagnosis_entries(
    tasks: Sequence[DiagnosticTaskRecord],
) -> dict[str, AlertDiagnosisEntry]:
    """按 alertId 索引诊断，同一告警只保留最新任务。"""
    entries: dict[str, AlertDiagnosisEntry] = {}
    # 任务按创建时间升序遍历，后写入的较新任务覆盖旧值。
    for task in tasks:
        alert_id = _alert_diagnosis_id(task.input_payload)
        if alert_id is None:
            continue
        entries[alert_id] = AlertDiagnosisEntry(
            diagnostic_id=task.id,
            status=task.status,
            created_at=task.created_at,
        )
    return entries


async def _alert_diagnosis_entries_for_user(
    app: FastAPI, *, owner_user_id: str
) -> dict[str, AlertDiagnosisEntry]:
    repositories = cast(MemoryRepositories, app.state.memory_repositories)
    # 只读取当前用户的诊断任务，即使 alertId 相同也不会串用户。
    tasks = await repositories.diagnostics.list_tasks(owner_user_id=owner_user_id)
    return _alert_diagnosis_entries(tasks)


def _alert_diagnosis_age_seconds(created_at: datetime, now: datetime) -> float:
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return (now - created_at).total_seconds()


async def _start_auto_diagnoses(
    app: FastAPI,
    *,
    alerts: Sequence[ActiveAlert],
    previous_alert_ids: set[str],
    settings: AutoDiagnosisSettings,
    now: datetime | None = None,
) -> int:
    """为满足策略的新告警各创建一个持久诊断任务；返回本轮启动数量。"""
    # 只处理本轮新出现且级别匹配的告警，避免对存量告警重复触发。
    candidates = [
        alert
        for alert in alerts
        if alert.id not in previous_alert_ids and settings.matches(alert)
    ]
    if not candidates:
        return 0
    owner = await _auth_repository_from_app(app).find_user_by_email(settings.owner_email)
    if owner is None:
        # 找不到 ownerEmail 对应用户时只记录事件，绝不把诊断归到任意用户。
        emit_event(logger, "alerts.auto_diagnosis.owner_missing")
        return 0
    repositories = cast(MemoryRepositories, app.state.memory_repositories)
    current = now or datetime.now(timezone.utc)
    last_by_alert = _alert_diagnosis_entries(
        await repositories.diagnostics.list_tasks(owner_user_id=owner.id)
    )
    started = 0
    for alert in candidates:
        # 每轮触发上限，防止告警风暴瞬间打满任务队列与 LLM 配额。
        if started >= settings.max_per_poll:
            break
        previous = last_by_alert.get(alert.id)
        # 去重窗口内同一告警已有诊断则跳过，避免反复诊断同一事件。
        if (
            previous is not None
            and _alert_diagnosis_age_seconds(previous.created_at, current)
            < settings.dedupe_window_seconds
        ):
            continue
        query = auto_diagnosis_query(alert)
        task = await repositories.diagnostics.create_task(
            owner_user_id=owner.id,
            task_id=f"diagnostic_{uuid4().hex}",
            status="accepted",
            query=query,
            input_payload=auto_diagnosis_input_payload(alert),
            result_payload={},
        )
        await _background_job_repository_from_app(app).enqueue(
            owner_user_id=owner.id,
            job_id=f"job_{uuid4().hex}",
            kind="aiops_diagnosis",
            resource_type="aiops_diagnostic",
            resource_id=task.id,
            payload={"diagnosticId": task.id, "alertId": alert.id},
            max_attempts=1,
            timeout_seconds=1800,
        )
        started += 1
    if started > 0:
        # 只有真正入队后才启动 runtime，并记录本轮数量。
        await _background_job_runtime_from_app(app).start()
        emit_event(logger, "alerts.auto_diagnosis.started", count=started)
    return started


def _alert_poll_job_handler(
    app: FastAPI,
) -> Callable[[BackgroundJobContext], Awaitable[None]]:
    """全局告警轮询：失败保留旧快照，成功原子替换，并在末尾自我续排。"""

    async def handle(context: BackgroundJobContext) -> None:
        await context.raise_if_cancelled()
        provider = _active_alert_provider(_request_for_app(app))
        interval = _alert_poll_interval_seconds(app)
        try:
            alerts = await provider.list_active_alerts()
        except AlertProviderError as exc:
            # 抓取失败时保留上一版快照，绝不能把界面清空成“当前无告警”。
            logger.warning("Alert poll failed; keeping previous snapshot: %s", exc)
        else:
            repository = _active_alert_repository_from_app(app)
            # 先记录上一轮告警 id，用于判断哪些是本轮新出现的告警。
            previous_alert_ids = {
                alert.id for alert in await repository.list_active_alerts()
            }
            revision = await repository.replace_snapshot(
                alerts=[_active_alert_record(alert) for alert in alerts],
            )
            emit_event(logger, "alerts.poll.completed", revision=revision, count=len(alerts))
            try:
                settings = _auto_diagnosis_settings(app)
                if settings is not None:
                    await _start_auto_diagnoses(
                        app,
                        alerts=alerts,
                        previous_alert_ids=previous_alert_ids,
                        settings=settings,
                    )
            except Exception:
                # 自动诊断只是轮询的副作用：失败不能中断自我续排的轮询链。
                logger.exception("Automatic alert diagnosis failed.")
        # 成功或失败都续排下一轮；间隔取配置值，默认 10 秒。
        await context.repository.enqueue(
            owner_user_id=context.job.owner_user_id,
            job_id=f"job_{uuid4().hex}",
            kind="alert_poll",
            resource_type=_ALERT_POLL_RESOURCE_TYPE,
            resource_id=_ALERT_POLL_RESOURCE_ID,
            payload={},
            max_attempts=3,
            timeout_seconds=120,
            available_at=datetime.now(timezone.utc) + timedelta(seconds=interval),
        )

    return handle


def _request_for_app(app: FastAPI) -> Request:
    return Request(
        {
            "type": "http",
            "app": app,
            "headers": [],
            "method": "GET",
            "path": "/_background",
            "query_string": b"",
            "scheme": "http",
            "server": ("127.0.0.1", 8000),
            "client": ("127.0.0.1", 0),
            "root_path": "",
        }
    )


async def _cancel_background_resource(request: Request, job: BackgroundJobRecord) -> None:
    repositories = _memory_repositories(request)
    if job.resource_type == "document_index_task":
        await repositories.document_index_tasks.mark_cancelled(
            owner_user_id=job.owner_user_id,
            task_id=job.resource_id,
        )
    if job.resource_type == "aiops_diagnostic":
        await repositories.diagnostics.update_task(
            owner_user_id=job.owner_user_id,
            task_id=job.resource_id,
            status="cancelled",
            completed_at=datetime.now(timezone.utc),
        )


def _background_job_payload(job: BackgroundJobRecord) -> dict[str, object]:
    return {
        "id": job.id,
        "ownerUserId": job.owner_user_id,
        "kind": job.kind,
        "resourceType": job.resource_type,
        "resourceId": job.resource_id,
        "status": job.status,
        "attempt": job.attempt,
        "maxAttempts": job.max_attempts,
        "timeoutSeconds": job.timeout_seconds,
        "availableAt": job.available_at.isoformat(),
        "cancelRequestedAt": (
            job.cancel_requested_at.isoformat() if job.cancel_requested_at else None
        ),
        "retryOfJobId": job.retry_of_job_id,
        "errorMessage": job.error_message,
        "createdAt": job.created_at.isoformat(),
        "updatedAt": job.updated_at.isoformat(),
        "startedAt": job.started_at.isoformat() if job.started_at else None,
        "completedAt": job.completed_at.isoformat() if job.completed_at else None,
    }


def _background_job_error_event() -> dict[str, object]:
    category, http_status, message = ERROR_DEFINITIONS["SYSTEM_INTERNAL_ERROR"]
    return {
        "id": f"evt_{uuid4().hex}",
        "type": "error",
        "channel": "aiops",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "error": {
            "code": "SYSTEM_INTERNAL_ERROR",
            "category": category,
            "httpStatus": http_status,
            "message": message,
        },
    }


def _user_feedback_payload(record: UserFeedbackRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "ownerUserId": record.owner_user_id,
        "targetType": record.target_type,
        "targetId": record.target_id,
        "subjectId": record.subject_id,
        "rating": record.rating,
        "reason": record.reason,
        "comment": record.comment,
        "correction": record.correction,
        "createdAt": record.created_at.isoformat(),
        "updatedAt": record.updated_at.isoformat(),
    }


def _mcp_connection_payload(record: McpConnectionRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "ownerUserId": record.owner_user_id,
        "name": record.name,
        "transport": record.transport,
        "url": record.url,
        "enabled": record.enabled,
        "timeoutSeconds": record.timeout_seconds,
        "retries": record.retries,
        "lastCheck": (
            {
                "ok": record.last_check_ok,
                "toolCount": record.last_tool_count or 0,
                "tools": record.last_tools,
                "error": record.last_error,
                "checkedAt": (
                    record.last_checked_at.isoformat() if record.last_checked_at else None
                ),
            }
            if record.last_check_ok is not None
            else None
        ),
        "createdAt": record.created_at.isoformat(),
        "updatedAt": record.updated_at.isoformat(),
    }


def _prometheus_source_payload(record: PrometheusSourceRecord) -> dict[str, object]:
    """序列化数据源；password 永不出现在 payload 中。"""
    return {
        "id": record.id,
        "ownerUserId": record.owner_user_id,
        "name": record.name,
        "baseUrl": record.base_url,
        "username": record.username,
        "enabled": record.enabled,
        "timeoutSeconds": record.timeout_seconds,
        "maxSeries": record.max_series,
        "lastCheck": (
            {
                "ok": record.last_check_ok,
                "error": record.last_error,
                "checkedAt": (
                    record.last_checked_at.isoformat() if record.last_checked_at else None
                ),
            }
            if record.last_check_ok is not None
            else None
        ),
        "createdAt": record.created_at.isoformat(),
        "updatedAt": record.updated_at.isoformat(),
    }


def _prometheus_query_payload(query: str, series: list[MetricSeries]) -> dict[str, object]:
    """把 MetricSeries 转成契约的 series 形状；时间戳统一为毫秒。"""
    return {
        "query": query,
        "series": [
            {
                "metric": item.metric,
                "points": [
                    {"timestamp": int(timestamp * 1000), "value": value}
                    for timestamp, value in item.values
                ],
            }
            for item in series
        ],
    }


def _memory_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    return cast(async_sessionmaker[AsyncSession], request.app.state.memory_session_factory)


async def _runtime_dependency_payload(request: Request) -> dict[str, dict[str, object]]:
    """并行探测四类运行时依赖；任一失败只影响自己的条目。"""
    sqlite_result, milvus_result, llm_result, mcp_result = await asyncio.gather(
        _sqlite_readiness_payload(request),
        _milvus_readiness_payload(request),
        _llm_readiness_payload(request),
        _mcp_readiness_payload(request),
    )
    return {
        "sqlite": sqlite_result,
        "milvus": milvus_result,
        "llm": llm_result,
        "mcp": mcp_result,
    }


async def _sqlite_readiness_payload(request: Request) -> dict[str, object]:
    """用 SELECT 1 探测数据库；异常只返回安全错误文案。"""
    # 不返回连接串或异常原文，避免就绪端点泄露内部拓扑。
    started_at = monotonic()
    try:
        async with _memory_session_factory(request)() as session:
            await session.execute(sql_text("SELECT 1"))
    except Exception:
        return {
            "ok": False,
            "engine": "sqlite",
            "latencyMs": _elapsed_ms(started_at),
            "error": "SQLite is unavailable.",
        }
    return {
        "ok": True,
        "engine": "sqlite",
        "latencyMs": _elapsed_ms(started_at),
        "error": None,
    }


async def _milvus_readiness_payload(request: Request) -> dict[str, object]:
    """在线程池中执行 Milvus health_check，避免同步客户端阻塞事件循环。"""
    try:
        result = await run_in_threadpool(_vector_store(request).health_check)
    except Exception:
        return {
            "ok": False,
            "uri": None,
            "collectionName": None,
            "latencyMs": 0.0,
            "error": "Milvus is unavailable.",
        }
    payload = _milvus_health_payload(result)
    payload["error"] = None if result.ok else "Milvus is unavailable."
    return payload


async def _llm_readiness_payload(request: Request) -> dict[str, object]:
    """探测 LLM provider 就绪；只暴露 provider/model/baseUrl 等非敏感元数据。"""
    try:
        result = await _llm_provider(request).check_readiness()
    except Exception:
        return {
            "ok": False,
            "provider": None,
            "model": None,
            "baseUrl": None,
            "latencyMs": 0.0,
            "error": "LLM provider is unavailable.",
        }
    return {
        "ok": result.ok,
        "provider": result.provider,
        "model": result.model,
        "baseUrl": result.base_url,
        "latencyMs": result.latency_ms,
        "error": None if result.ok else "LLM provider is unavailable.",
    }


async def _mcp_readiness_payload(request: Request) -> dict[str, object]:
    """探测 MCP 就绪；字段类型显式校验，异常一律降级为不可用。"""
    try:
        result = await _mcp_client(request).readiness()
    except Exception:
        return {
            "ok": False,
            "endpoint": None,
            "toolCount": 0,
            "error": "MCP server is unavailable.",
        }
    is_ready = result.get("ok") is True
    endpoint = result.get("endpoint")
    tool_count = result.get("toolCount")
    return {
        "ok": is_ready,
        "endpoint": endpoint if isinstance(endpoint, str) else None,
        "toolCount": tool_count if isinstance(tool_count, int) else 0,
        "error": None if is_ready else "MCP server is unavailable.",
    }


def _configuration_check_payload(request: Request) -> dict[str, dict[str, object]]:
    """逐段加载配置并独立捕获异常，便于一次报告多个配置问题。"""
    # 只返回配置项名称与安全文案，绝不序列化密钥、token 或云凭据。
    config_path = request.app.state.project_config_path
    configuration: dict[str, dict[str, object]] = {}
    try:
        load_memory_database_settings(config_path=config_path)
    except Exception:
        configuration["sqlite"] = {
            "valid": False,
            "engine": "sqlite",
            "error": "SQLite configuration is invalid.",
        }
    else:
        configuration["sqlite"] = {"valid": True, "engine": "sqlite", "error": None}
    try:
        llm_config = load_llm_provider_config(config_path=config_path)
    except Exception:
        configuration["llm"] = {"valid": False, "error": "LLM configuration is invalid."}
    else:
        configuration["llm"] = {
            "valid": True,
            "provider": llm_config.provider,
            "model": llm_config.chat_model,
            "baseUrl": llm_config.base_url,
            "error": None,
        }
    try:
        vector_config = load_milvus_vector_store_settings(config_path=config_path)
    except Exception:
        configuration["milvus"] = {"valid": False, "error": "Milvus configuration is invalid."}
    else:
        configuration["milvus"] = {
            "valid": True,
            "uri": vector_config.uri,
            "collectionName": vector_config.collection_name,
            "error": None,
        }
    try:
        mcp_config = project_config_section("mcp", config_path=config_path)
        mcp_endpoint = required_str(mcp_config, "clsSseUrl")
        required_int(mcp_config, "timeoutSeconds")
        required_int(mcp_config, "retries")
    except Exception:
        configuration["mcp"] = {"valid": False, "error": "MCP configuration is invalid."}
    else:
        configuration["mcp"] = {"valid": True, "endpoint": mcp_endpoint, "error": None}
    try:
        tracing_settings = load_tracing_settings(config_path=config_path)
    except Exception:
        configuration["langfuse"] = {
            "valid": False,
            "enabled": None,
            "error": "Langfuse configuration is invalid.",
        }
    else:
        configuration["langfuse"] = (
            {"valid": True, "enabled": False, "error": None}
            if tracing_settings is None
            else {
                "valid": True,
                "enabled": True,
                "host": tracing_settings.host,
                "error": None,
            }
        )
    return configuration


def _elapsed_ms(started_at: float) -> float:
    return round((monotonic() - started_at) * 1000, 3)


def _vector_store(request: Request) -> MilvusHealthCheckProvider:
    return cast(MilvusHealthCheckProvider, request.app.state.vector_store)


def _document_vector_store(request: Request) -> DocumentVectorStoreProvider:
    return cast(DocumentVectorStoreProvider, request.app.state.vector_store)


def _embedding_model(request: Request) -> EmbeddingModel:
    model = request.app.state.embedding_model
    if model is None:
        model = build_default_llm_provider(
            config_path=request.app.state.project_config_path
        ).create_embedding_model()
        request.app.state.embedding_model = model
    return cast(EmbeddingModel, model)


def _rerank_model(request: Request) -> RerankModel:
    model = request.app.state.rerank_model
    if model is None:
        model = _llm_provider(request).create_rerank_model()
        request.app.state.rerank_model = model
    return cast(RerankModel, model)


def _llm_provider(request: Request) -> LlmProvider:
    provider = request.app.state.llm_provider
    if provider is None:
        provider = build_default_llm_provider(config_path=request.app.state.project_config_path)
        request.app.state.llm_provider = provider
    return cast(LlmProvider, provider)


_RETRIEVAL_CACHE_UNSET = object()


def _retrieval_cache(request: Request) -> RetrievalCache | None:
    cached = getattr(request.app.state, "retrieval_cache", _RETRIEVAL_CACHE_UNSET)
    if cached is _RETRIEVAL_CACHE_UNSET:
        cached = build_retrieval_cache(config_path=request.app.state.project_config_path)
        request.app.state.retrieval_cache = cached
    return cast(RetrievalCache | None, cached)


_TRACING_PROVIDER_UNSET = object()


def _tracing_provider(request: Request) -> TracingCallbackProvider | None:
    """Lazily build the optional Langfuse tracing provider; None when disabled.

    Mirrors ``_promql_provider``: tracing is a bypass capability, so a missing
    ``langfuse`` section keeps every runner exactly as before. Configuration
    errors surface via /config/check and on first use, matching other
    misconfigurations.
    """
    cached = getattr(request.app.state, "tracing_provider", _TRACING_PROVIDER_UNSET)
    if cached is _TRACING_PROVIDER_UNSET:
        cached = build_tracing_provider(config_path=request.app.state.project_config_path)
        request.app.state.tracing_provider = cached
    return cast(TracingCallbackProvider | None, cached)


def _context_window_tokens(request: Request) -> int:
    cached = getattr(request.app.state, "llm_context_window_tokens", None)
    if isinstance(cached, int):
        return cached
    resolved = load_llm_provider_config(
        config_path=request.app.state.project_config_path
    ).context_window_tokens
    request.app.state.llm_context_window_tokens = resolved
    return resolved


def _invalidate_llm_runtime_cache(app: FastAPI) -> None:
    """Reset cached LLM runtime objects so the next request rebuilds them from config.

    Test-injected providers are never clobbered. The retrieval cache must be
    rebuilt as well: the chat/AIOps runners capture it together with the
    embedding model, so an embedding change would otherwise keep serving
    vectors cached for the previous model.
    """
    injected = cast(dict[str, bool], getattr(app.state, "injected_providers", {}))
    for key in (
        "embedding_model",
        "rerank_model",
        "llm_provider",
        "chat_agent_runner",
        "aiops_diagnostic_runner",
    ):
        if not injected.get(key, False):
            setattr(app.state, key, None)
    app.state.llm_context_window_tokens = None
    app.state.retrieval_cache = _RETRIEVAL_CACHE_UNSET
    # tracing_provider 不能通过 create_app 注入，无条件复位到 sentinel 即可。
    app.state.tracing_provider = _TRACING_PROVIDER_UNSET


def _chat_memory_service(request: Request) -> ChatMemoryService:
    return ChatMemoryService(
        repositories=_memory_repositories(request),
        llm_provider=_llm_provider(request),
        context_window_tokens=_context_window_tokens(request),
        tracing_provider=_tracing_provider(request),
    )


async def _chat_memory_context(
    request: Request, *, owner_user_id: str
) -> tuple[ChatMemoryService, str]:
    service = _chat_memory_service(request)
    prompt_builder = ChatStreamingService(
        repositories=_memory_repositories(request),
        agent_runner=_chat_agent_runner(request),
        memory_service=service,
    )
    return service, await prompt_builder.build_system_prompt(owner_user_id=owner_user_id)


def _chat_agent_runner(request: Request) -> ChatAgentRunner:
    runner = request.app.state.chat_agent_runner
    if runner is None:
        retrieval_tool = KnowledgeRetrievalTool(
            embedding_model=_embedding_model(request),
            vector_store=cast(RetrievalVectorStore, _vector_store(request)),
            rerank_model=_rerank_model(request),
            cache=_retrieval_cache(request),
        )
        runner = LangChainChatAgentRunner(
            llm_provider=_llm_provider(request),
            retrieval_tool=retrieval_tool,
            mcp_client_provider=_mcp_connection_service(request),
            tracing_provider=_tracing_provider(request),
        )
        request.app.state.chat_agent_runner = runner
    return cast(ChatAgentRunner, runner)


def _mcp_client(request: Request) -> LocalMcpClient:
    config = project_config_section("mcp", config_path=request.app.state.project_config_path)
    return LocalMcpClient(
        required_str(config, "clsSseUrl"),
        timeout_seconds=required_int(config, "timeoutSeconds"),
        retries=required_int(config, "retries"),
    )


def _active_alert_provider(request: Request) -> ActiveAlertProvider:
    provider = cast(ActiveAlertProvider | None, request.app.state.alert_provider)
    if provider is None:
        provider = build_alertmanager_alert_provider(
            config_path=request.app.state.project_config_path
        )
        request.app.state.alert_provider = provider
    return provider


_PROMQL_PROVIDER_UNSET = object()


def _promql_provider(request: Request) -> PromqlProvider | None:
    """Lazily build the configured Prometheus provider; tolerate it being unconfigured.

    Metric evidence is optional: when the ``prometheus`` config section is absent or
    invalid (for example the empty placeholder in a fresh checkout) the diagnostic graph
    simply runs log-only instead of failing the whole AIOps feature.
    """
    cached = getattr(request.app.state, "promql_provider", _PROMQL_PROVIDER_UNSET)
    if cached is _PROMQL_PROVIDER_UNSET:
        try:
            cached = build_promql_provider(config_path=request.app.state.project_config_path)
        except MetricQueryError:
            cached = None
        request.app.state.promql_provider = cached
    return cast(PromqlProvider | None, cached)


def _aiops_diagnostic_runner(request: Request) -> AiopsDiagnosticRunner:
    runner = cast(AiopsDiagnosticRunner | None, request.app.state.aiops_diagnostic_runner)
    if runner is None:
        mcp_client_provider = _mcp_connection_service(request)
        runner = AiopsDiagnosticService(
            repositories=_memory_repositories(request),
            llm_provider=_llm_provider(request),
            retrieval_tool=KnowledgeRetrievalTool(
                embedding_model=_embedding_model(request),
                vector_store=cast(RetrievalVectorStore, _vector_store(request)),
                rerank_model=_rerank_model(request),
                cache=_retrieval_cache(request),
            ),
            mcp_client_provider=mcp_client_provider,
            promql_provider=_promql_provider(request),
            log_store=build_log_store(
                config_path=request.app.state.project_config_path,
                mcp_client_provider=mcp_client_provider,
            ),
            case_persistor=DiagnosisCasePersistor(
                repositories=_memory_repositories(request),
                index_task_scheduler=_index_task_scheduler(request),
            ),
            tracing_provider=_tracing_provider(request),
        )
        request.app.state.aiops_diagnostic_runner = runner
    return runner


_CHUNKING_SETTINGS_UNSET = object()


def _chunking_settings(app: FastAPI) -> ChunkingSettings:
    cached = getattr(app.state, "chunking_settings", _CHUNKING_SETTINGS_UNSET)
    if cached is _CHUNKING_SETTINGS_UNSET:
        cached = load_chunking_settings(config_path=app.state.project_config_path)
        app.state.chunking_settings = cached
    return cast(ChunkingSettings, cached)


def _document_indexing_service(request: Request) -> DocumentIndexingService:
    settings = _chunking_settings(request.app)
    return DocumentIndexingService(
        repositories=_memory_repositories(request),
        embedding_model=_embedding_model(request),
        vector_store=_document_vector_store(request),
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )


def _document_indexing_service_from_app(app: FastAPI) -> DocumentIndexingService:
    settings = _chunking_settings(app)
    return DocumentIndexingService(
        repositories=cast(MemoryRepositories, app.state.memory_repositories),
        embedding_model=cast(EmbeddingModel, app.state.embedding_model)
        if app.state.embedding_model is not None
        else build_default_llm_provider(
            config_path=app.state.project_config_path
        ).create_embedding_model(),
        vector_store=cast(DocumentVectorStoreProvider, app.state.vector_store),
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )


def _index_task_scheduler(request: Request) -> DocumentIndexTaskScheduler:
    return cast(DocumentIndexTaskScheduler, request.app.state.index_task_scheduler)


def _bearer_token(credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ApiErrorException("AUTH_UNAUTHENTICATED")
    return credentials.credentials


def _api_error(exc: AuthError) -> ApiErrorException:
    return ApiErrorException(exc.code, str(exc))


def _llm_config_view_payload(view: LlmConfigView) -> dict[str, object]:
    return {
        "provider": view.provider,
        "apiKeyConfigured": view.api_key_configured,
        "apiKeyLast4": view.api_key_last4,
        "baseUrl": view.base_url,
        "chatModel": view.chat_model,
        "contextWindowTokens": view.context_window_tokens,
        "embeddingModel": view.embedding_model,
        "embeddingDimensions": view.embedding_dimensions,
        "rerankModel": view.rerank_model,
        "rerankUrl": view.rerank_url,
        "temperature": view.temperature,
        "timeoutSeconds": view.timeout_seconds,
        "maxRetries": view.max_retries,
        "langfuseEnabled": view.langfuse_enabled,
        "langfuseHost": view.langfuse_host,
        "langfusePublicKeyConfigured": view.langfuse_public_key_configured,
        "langfusePublicKeyLast4": view.langfuse_public_key_last4,
        "langfuseSecretKeyConfigured": view.langfuse_secret_key_configured,
        "langfuseSecretKeyLast4": view.langfuse_secret_key_last4,
    }


def _user_payload(user: UserRecord) -> dict[str, str]:
    return {
        "id": user.id,
        "email": user.email,
        "displayName": user.display_name,
        "createdAt": user.created_at.isoformat(),
    }


def _auth_result_payload(result: AuthResult) -> dict[str, object]:
    return {
        "user": _user_payload(result.user),
        "accessToken": result.access_token,
        "tokenType": result.token_type,
    }


def _chat_session_payload(
    record: ChatSessionRecord, context_window_tokens: int
) -> dict[str, object]:
    return {
        "id": record.id,
        "ownerUserId": record.owner_user_id,
        "title": record.title or "New chat",
        "createdAt": record.created_at.isoformat(),
        "updatedAt": record.updated_at.isoformat(),
        "memory": memory_payload(record, context_window_tokens),
    }


def _chat_message_payload(message: ChatMessageRecord) -> dict[str, object]:
    return {
        "id": message.id,
        "ownerUserId": message.owner_user_id,
        "sessionId": message.session_id,
        "role": message.role,
        "content": message.content,
        "metadata": message.metadata,
        "createdAt": message.created_at.isoformat(),
    }


def _agent_tool_call_audit_payload(record: AgentToolCallAuditRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "ownerUserId": record.owner_user_id,
        "sessionId": record.chat_session_id,
        "diagnosticTaskId": record.diagnostic_task_id,
        "toolName": record.tool_name,
        "status": record.status,
        "arguments": record.arguments,
        "resultSummary": record.result_summary,
        "errorMessage": record.error_message,
        "startedAt": record.started_at.isoformat(),
        "completedAt": record.completed_at.isoformat() if record.completed_at is not None else None,
        "durationMs": record.duration_ms,
        "createdAt": record.created_at.isoformat(),
    }


def _normalize_chat_title(title: str | None) -> str:
    if title is None:
        return "New chat"
    normalized = " ".join(title.split())
    if normalized == "":
        return "New chat"
    return normalized[:80]


async def _maybe_generate_chat_title(
    repositories: MemoryRepositories,
    *,
    user_id: str,
    session: ChatSessionRecord,
    message_role: str,
    message_content: str,
) -> ChatSessionRecord:
    if message_role != "user" or session.title not in {None, "New chat"}:
        refreshed = await repositories.chat.get_session(
            owner_user_id=user_id,
            session_id=session.id,
        )
        return refreshed or session
    generated_title = _normalize_chat_title(message_content)
    updated = await repositories.chat.update_session_title(
        owner_user_id=user_id,
        session_id=session.id,
        title=generated_title,
    )
    return updated or session


def _diagnostic_task_payload(
    record: DiagnosticTaskRecord,
    *,
    reports: Sequence[DiagnosticReportRecord] = (),
) -> dict[str, object]:
    return {
        "id": record.id,
        "ownerUserId": record.owner_user_id,
        "status": record.status,
        "query": record.query,
        "inputPayload": record.input_payload,
        "resultPayload": record.result_payload,
        "createdAt": record.created_at.isoformat(),
        "updatedAt": record.updated_at.isoformat(),
        "completedAt": record.completed_at.isoformat() if record.completed_at is not None else None,
        "reports": [_diagnostic_report_payload(report) for report in reports],
    }


def _alert_diagnosis_payload(
    payload: dict[str, object], diagnosis: AlertDiagnosisEntry | None
) -> dict[str, object]:
    if diagnosis is not None:
        payload["diagnosticId"] = diagnosis.diagnostic_id
        payload["diagnosisStatus"] = diagnosis.status
    return payload


def _active_alert_payload(
    alert: ActiveAlert, diagnosis: AlertDiagnosisEntry | None = None
) -> dict[str, object]:
    return _alert_diagnosis_payload(
        {
            "id": alert.id,
            "source": alert.source,
            "alertName": alert.alert_name,
            "service": alert.service,
            "severity": alert.severity,
            "status": alert.status,
            "startsAt": alert.starts_at,
            "summary": alert.summary,
            "labels": alert.labels,
            "annotations": alert.annotations,
            "context": alert.context,
        },
        diagnosis,
    )


def _active_alert_record(alert: ActiveAlert) -> ActiveAlertRecord:
    return ActiveAlertRecord(
        id=alert.id,
        source=alert.source,
        alert_name=alert.alert_name,
        service=alert.service,
        severity=alert.severity,
        status=alert.status,
        starts_at=alert.starts_at,
        summary=alert.summary,
        labels=dict(alert.labels),
        annotations=dict(alert.annotations),
        context=dict(alert.context),
    )


def _active_alert_record_payload(
    record: ActiveAlertRecord, diagnosis: AlertDiagnosisEntry | None = None
) -> dict[str, object]:
    return _alert_diagnosis_payload(
        {
            "id": record.id,
            "source": record.source,
            "alertName": record.alert_name,
            "service": record.service,
            "severity": record.severity,
            "status": record.status,
            "startsAt": record.starts_at,
            "summary": record.summary,
            "labels": record.labels,
            "annotations": record.annotations,
            "context": record.context,
        },
        diagnosis,
    )


def alert_snapshot_event(
    records: Sequence[ActiveAlertRecord],
    diagnosis: Mapping[str, AlertDiagnosisEntry] | None = None,
) -> dict[str, object]:
    """构造 alerts.snapshot 事件：每次推送全量快照，避免前端做增量合并。"""
    return {
        "id": f"evt_{uuid4().hex}",
        "type": "alerts.snapshot",
        "channel": "aiops",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "items": [
            _active_alert_record_payload(
                record, None if diagnosis is None else diagnosis.get(record.id)
            )
            for record in records
        ],
    }


async def alert_snapshot_stream(
    repository: ActiveAlertRepository,
    *,
    poll_seconds: float = 0.25,
    diagnosis_loader: Callable[
        [], Awaitable[Mapping[str, AlertDiagnosisEntry]]
    ] | None = None,
) -> AsyncIterator[str]:
    """按 revision 变化推送全量快照；revision 不变时不推送，避免无效流量。"""
    last_revision = 0
    while True:
        revision = await repository.latest_revision()
        # revision 单调递增且空快照也会 +1，因此前端能感知“告警被清空”。
        if revision > last_revision:
            last_revision = revision
            snapshot = await repository.list_active_alerts()
            # 每次推送都重新加载诊断进度，保证附加状态与任务表一致。
            diagnosis = await diagnosis_loader() if diagnosis_loader is not None else None
            yield encode_sse(alert_snapshot_event(snapshot, diagnosis))
        await asyncio.sleep(poll_seconds)


def _diagnostic_report_payload(
    record: DiagnosticReportRecord,
    *,
    evidence_ids: Sequence[str] = (),
) -> dict[str, object]:
    return {
        "id": record.id,
        "title": record.title,
        "content": record.content,
        "payload": record.payload,
        **({"diagnosis": record.payload["diagnosis"]} if "diagnosis" in record.payload else {}),
        "evidenceIds": list(evidence_ids),
        "createdAt": record.created_at.isoformat(),
    }


def _diagnostic_case_payload(record: DiagnosticCaseRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "ownerUserId": record.owner_user_id,
        "taskId": record.task_id,
        "reportId": record.report_id,
        "documentId": record.document_id,
        "indexTaskId": record.index_task_id,
        "alertName": record.alert_name,
        "service": record.service,
        "keywords": record.keywords,
        "rootCause": record.root_cause,
        "remediation": record.remediation,
        "summary": record.summary,
        "evidenceIds": record.evidence_ids,
        "reviewStatus": record.review_status,
        "confirmedBy": record.confirmed_by,
        "confirmedAt": record.confirmed_at.isoformat() if record.confirmed_at else None,
        "createdAt": record.created_at.isoformat(),
    }


def _diagnostic_step_payload(record: DiagnosticStepRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "taskId": record.task_id,
        "sequence": record.sequence,
        "phase": record.phase,
        "status": record.status,
        "payload": record.payload,
        "createdAt": record.created_at.isoformat(),
    }


def _diagnostic_evidence_payload(record: DiagnosticEvidenceRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "taskId": record.task_id,
        "stepId": record.step_id,
        "toolCallId": record.tool_call_id,
        "kind": record.kind,
        "source": record.source,
        "summary": record.summary,
        "payload": record.payload,
        "createdAt": record.created_at.isoformat(),
    }


def _diagnostic_case_content(
    task: DiagnosticTaskRecord,
    report: DiagnosticReportRecord,
    evidence: Sequence[DiagnosticEvidenceRecord],
) -> str:
    lines = [
        "# AIOps Diagnostic Case",
        "",
        f"Diagnostic task: {task.id}",
        f"Report: {report.id}",
        "",
        "## Incident query",
        task.query,
        "",
        "## Evidence-backed report",
        report.content,
        "",
        "## Evidence summaries",
    ]
    lines.extend(f"- [{item.kind}] {item.source}: {item.summary[:500]}" for item in evidence)
    return "\n".join(lines)


def _report_evidence_link_payload(record: ReportEvidenceLinkRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "taskId": record.task_id,
        "reportId": record.report_id,
        "evidenceId": record.evidence_id,
        "createdAt": record.created_at.isoformat(),
    }


def _graph_checkpoint_payload(record: GraphCheckpointRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "taskId": record.task_id,
        "threadId": record.thread_id,
        "checkpointNamespace": record.checkpoint_ns,
        "checkpointId": record.checkpoint_id,
        "payload": record.checkpoint_payload,
        "metadata": record.metadata,
        "createdAt": record.created_at.isoformat(),
    }


def _report_evidence_ids(
    links: Sequence[ReportEvidenceLinkRecord],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for link in links:
        result.setdefault(link.report_id, []).append(link.evidence_id)
    return result


def _knowledge_document_payload(record: KnowledgeDocumentRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "knowledgeBaseId": record.knowledge_base_id,
        "ownerUserId": record.owner_user_id,
        "filename": record.filename,
        "sizeBytes": record.size_bytes,
        "mimeType": record.mime_type,
        "contentHash": record.content_hash,
        "status": record.status,
        "indexStatus": record.index_status,
        "chunking": _document_chunking_payload(record),
        "uploadedAt": record.uploaded_at.isoformat(),
        "updatedAt": record.updated_at.isoformat(),
        "source": record.source,
    }


def _document_chunking_payload(record: KnowledgeDocumentRecord) -> dict[str, object]:
    chunking = record.metadata.get("chunking")
    if isinstance(chunking, dict):
        return cast(dict[str, object], chunking)
    return {
        "strategy": "fixed-character",
        "maxCharacters": DEFAULT_CHUNK_SIZE,
        "overlapCharacters": DEFAULT_CHUNK_OVERLAP,
    }


def _parse_chunking_configuration(raw: str) -> dict[str, object]:
    default: dict[str, object] = {
        "strategy": "fixed-character",
        "maxCharacters": DEFAULT_CHUNK_SIZE,
        "overlapCharacters": DEFAULT_CHUNK_OVERLAP,
    }
    if not raw.strip():
        return default
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ApiErrorException("VALIDATION_INVALID_ARGUMENT") from exc
    if not isinstance(value, dict):
        raise ApiErrorException("VALIDATION_INVALID_ARGUMENT")
    mapping = cast(dict[str, object], value)
    strategy = mapping.get("strategy")
    if strategy not in {"fixed-character", "markdown-heading", "paragraph"}:
        raise ApiErrorException(
            "VALIDATION_INVALID_ARGUMENT",
            "分片策略只能是 fixed-character、markdown-heading 或 paragraph。",
        )
    if strategy != "fixed-character":
        return {"strategy": strategy}
    size = mapping.get("maxCharacters")
    overlap = mapping.get("overlapCharacters")
    if (
        not isinstance(size, int)
        or not isinstance(overlap, int)
        or size < 100
        or size > 5000
        or overlap < 0
        or overlap >= size
    ):
        raise ApiErrorException(
            "VALIDATION_INVALID_ARGUMENT",
            "固定字符分片需要 100-5000 的最大字符数，且 overlap 必须大于等于 0 并小于最大字符数。",
        )
    return {"strategy": strategy, "maxCharacters": size, "overlapCharacters": overlap}


def _runtime_chunk_size(configuration: dict[str, object]) -> int:
    if configuration.get("strategy") == "fixed-character":
        return cast(int, configuration["maxCharacters"])
    return DEFAULT_CHUNK_SIZE


def _runtime_chunk_overlap(configuration: dict[str, object]) -> int:
    if configuration.get("strategy") == "fixed-character":
        return cast(int, configuration["overlapCharacters"])
    return 0


def _decode_indexable_document(record: KnowledgeDocumentRecord) -> str:
    value = record.metadata.get("indexableText")
    return value if isinstance(value, str) else ""


def _chat_configuration_repository(request: Request) -> UserChatConfigurationRepository:
    repository = _memory_repositories(request).chat_configurations
    if repository is None:
        raise ApiErrorException("SYSTEM_INTERNAL_ERROR")
    return repository


def _chat_prompt_repository(request: Request) -> UserChatPromptRepository:
    repository = _memory_repositories(request).chat_prompts
    if repository is None:
        raise ApiErrorException("SYSTEM_INTERNAL_ERROR")
    return repository


def _chat_skill_repository(request: Request) -> UserChatSkillRepository:
    repository = _memory_repositories(request).chat_skills
    if repository is None:
        raise ApiErrorException("SYSTEM_INTERNAL_ERROR")
    return repository


async def _read_chat_configuration(
    request: Request,
    *,
    owner_user_id: str,
) -> tuple[list[UserChatPromptRecord], list[UserChatSkillRecord], UserChatConfigurationRecord]:
    prompt_repository = _chat_prompt_repository(request)
    skill_repository = _chat_skill_repository(request)
    configuration_repository = _chat_configuration_repository(request)
    default_prompt = await prompt_repository.ensure_default(
        owner_user_id=owner_user_id,
        label=DEFAULT_CHAT_PROMPT_LABEL,
        content=DEFAULT_CHAT_PROMPT_CONTENT,
    )
    configuration = await configuration_repository.get_or_create(
        owner_user_id=owner_user_id,
        system_prompt_id=default_prompt.id,
        skill_ids=[],
    )
    prompts = await prompt_repository.list(owner_user_id=owner_user_id)
    prompt_ids = {item.id for item in prompts}
    if configuration.system_prompt_id not in prompt_ids:
        configuration = await configuration_repository.update(
            owner_user_id=owner_user_id,
            system_prompt_id=default_prompt.id,
            skill_ids=configuration.skill_ids,
        )
    skills = await skill_repository.list(owner_user_id=owner_user_id)
    available_skill_ids = {item.id for item in skills}
    selected_skill_ids = [
        item for item in dict.fromkeys(configuration.skill_ids) if item in available_skill_ids
    ]
    if selected_skill_ids != configuration.skill_ids:
        configuration = await configuration_repository.update(
            owner_user_id=owner_user_id,
            system_prompt_id=configuration.system_prompt_id,
            skill_ids=selected_skill_ids,
        )
    return prompts, skills, configuration


def _chat_configuration_payload(
    prompts: list[UserChatPromptRecord],
    skills: list[UserChatSkillRecord],
    configuration: UserChatConfigurationRecord,
) -> dict[str, object]:
    return {
        "prompts": [_chat_prompt_payload(item) for item in prompts],
        "skills": [_chat_skill_payload(item) for item in skills],
        "selection": {
            "systemPromptId": configuration.system_prompt_id,
            "skillIds": configuration.skill_ids,
            "updatedAt": configuration.updated_at.isoformat(),
        },
    }


def _chat_prompt_payload(prompt: UserChatPromptRecord) -> dict[str, object]:
    return {
        "id": prompt.id,
        "label": prompt.label,
        "content": prompt.content,
        "isDefault": prompt.is_default,
        "createdAt": prompt.created_at.isoformat(),
        "updatedAt": prompt.updated_at.isoformat(),
    }


def _chat_skill_payload(skill: UserChatSkillRecord) -> dict[str, object]:
    return {
        "id": skill.id,
        "filename": skill.filename,
        "name": skill.name,
        "description": skill.description,
        "label": skill.name,
        "contentPreview": skill.description,
        "sizeBytes": skill.size_bytes,
        "createdAt": skill.created_at.isoformat(),
        "updatedAt": skill.updated_at.isoformat(),
    }


def _document_index_task_payload(record: DocumentIndexTaskRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "ownerUserId": record.owner_user_id,
        "knowledgeBaseId": record.knowledge_base_id,
        "documentId": record.document_id,
        "status": record.status,
        "failureReason": record.failure_reason,
        "retryOfTaskId": record.retry_of_task_id,
        "createdAt": record.created_at.isoformat(),
        "updatedAt": record.updated_at.isoformat(),
        "startedAt": record.started_at.isoformat() if record.started_at is not None else None,
        "completedAt": record.completed_at.isoformat() if record.completed_at is not None else None,
    }


def _milvus_health_payload(result: MilvusHealthCheckResult) -> dict[str, object]:
    return {
        "ok": result.ok,
        "uri": result.uri,
        "collectionName": result.collection_name,
        "latencyMs": result.latency_ms,
        "error": result.error,
    }


def _ensure_knowledge_base_access(user: UserRecord, knowledge_base_id: str) -> None:
    if knowledge_base_id != f"kb_{user.id}":
        raise ApiErrorException("AUTH_FORBIDDEN")


def _accessible_knowledge_base_ids(user: UserRecord) -> tuple[str, ...]:
    return (f"kb_{user.id}",)


def _validate_upload(file: UploadFile, content: bytes) -> None:
    filename = file.filename or ""
    suffix = PurePosixPath(filename).suffix.lower()
    mime_type = file.content_type or ""
    display_mime_type = mime_type or "empty"
    if not content:
        raise ApiErrorException(
            "VALIDATION_INVALID_ARGUMENT",
            "文件不能为空，请上传包含正文的 Markdown、TXT 或 PDF。",
        )
    if len(content) > DOCUMENT_MAX_SIZE_BYTES:
        raise ApiErrorException("VALIDATION_INVALID_ARGUMENT", "文件大小不能超过 10 MB。")
    if suffix not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise ApiErrorException(
            "VALIDATION_INVALID_ARGUMENT",
            "仅支持 Markdown(.md)、TXT(.txt) 与 PDF(.pdf) 文件。",
        )
    if suffix in TEXT_DOCUMENT_EXTENSIONS and mime_type not in MARKDOWN_DOCUMENT_MIME_TYPES:
        label = "TXT" if suffix == ".txt" else "Markdown"
        raise ApiErrorException(
            "VALIDATION_INVALID_ARGUMENT",
            f"{label} 文件的 MIME 类型不符合要求：{display_mime_type}。请上传 {suffix} 文件。",
        )
    if suffix == ".pdf" and mime_type not in PDF_DOCUMENT_MIME_TYPES:
        raise ApiErrorException(
            "VALIDATION_INVALID_ARGUMENT",
            f"PDF 文件的 MIME 类型不符合要求：{display_mime_type}。请上传有效的 .pdf 文件。",
        )


def _delete_document_vectors(
    request: Request,
    *,
    tenant_id: str,
    knowledge_base_id: str,
    document_id: str,
) -> None:
    try:
        _document_vector_store(request).delete_document_chunks(
            tenant_id=tenant_id,
            knowledge_base_id=knowledge_base_id,
            document_id=document_id,
        )
    except ApiErrorException:
        raise
    except Exception as exc:
        raise ApiErrorException("SYSTEM_INTERNAL_ERROR") from exc
