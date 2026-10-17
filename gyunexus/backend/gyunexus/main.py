import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .activity import Activity
from .agents.orchestrator import AgentOrchestrator
from .api import router
from .config import ROOT, Settings
from .context import ContextManager
from .conversation import ConversationEngine
from .db import Database
from .events import EventBus
from .llm import BudgetExceeded, LLMError, LLMGateway, LLMNotConfigured, LLMProvider, build_gateway
from .memory import MemoryManager
from .policy import Policy
from .proactive import ProactiveEngine
from .routing import ConversationRouter
from .scheduler import Scheduler
from .tools import ToolRegistry, build_registry

FRONTEND_DIST = ROOT / "frontend" / "dist"


@dataclass
class Services:
    settings: Settings
    db: Database
    bus: EventBus
    activity: Activity
    llm: LLMGateway
    tools: ToolRegistry
    policy: Policy
    memory: MemoryManager
    context: ContextManager
    conversation: ConversationEngine
    orchestrator: AgentOrchestrator
    proactive: ProactiveEngine
    scheduler: Scheduler
    background: set = field(default_factory=set)


def build_services(
    settings: Settings, provider: LLMProvider | None = None, http_transport: httpx.AsyncBaseTransport | None = None
) -> Services:
    db = Database(settings.db_url)
    bus = EventBus()
    activity = Activity(db, bus)
    llm = build_gateway(settings, db, provider)
    tools = build_registry(settings, http_transport)
    policy = Policy(tools, db, bus, activity)
    memory = MemoryManager(db, llm, activity, settings.memory_top_k)
    context = ContextManager(db, settings)
    orchestrator = AgentOrchestrator(settings, db, llm, memory, policy, tools, bus, activity)
    router = ConversationRouter(db, llm, settings, activity)
    conversation = ConversationEngine(
        db, llm, memory, context, policy, router, bus, activity, settings, on_new_memories=orchestrator.on_new_memories
    )
    proactive = ProactiveEngine(settings, db, llm, memory, context, policy, conversation, activity)
    scheduler = Scheduler(settings, db, llm, orchestrator, proactive, activity)
    return Services(
        settings, db, bus, activity, llm, tools, policy, memory, context, conversation, orchestrator, proactive, scheduler
    )


def create_app(
    settings: Settings | None = None,
    provider: LLMProvider | None = None,
    run_scheduler: bool = True,
    http_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = settings or Settings()
    svc = build_services(settings, provider, http_transport)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        svc.db.create_all()
        svc.orchestrator.register_agents()
        task = asyncio.create_task(svc.scheduler.run()) if run_scheduler else None
        svc.activity.record(
            "system", "startup", llm_configured=svc.llm.configured, model=svc.llm.model, autonomous=svc.scheduler.autonomous_enabled()
        )
        yield
        if task:
            task.cancel()

    app = FastAPI(title="GyuNexus", version="0.1.0", lifespan=lifespan)
    app.state.svc = svc
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(LLMNotConfigured)
    async def _not_configured(_: Request, e: LLMNotConfigured):
        return JSONResponse({"detail": "OPENAI_API_KEY is not set"}, status_code=503)

    @app.exception_handler(BudgetExceeded)
    async def _budget(_: Request, e: BudgetExceeded):
        return JSONResponse({"detail": str(e)}, status_code=429)

    @app.exception_handler(LLMError)
    async def _llm_error(_: Request, e: LLMError):
        return JSONResponse({"detail": str(e)}, status_code=502)

    app.include_router(router)
    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    return app
