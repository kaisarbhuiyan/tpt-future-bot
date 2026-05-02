import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.models.db_models import Base
from app.api.routes import router
from app.risk.drawdown_tracker import DrawdownTracker
from app.execution.paper_broker import PaperBroker
from app.scheduler.bot_scheduler import BotScheduler

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Config loader
# ------------------------------------------------------------------ #

def load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config" / "rules.yaml"
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def setup_database(database_url: str):
    engine = create_async_engine(database_url, echo=False, future=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, session_factory


def setup_logging() -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_file = os.getenv("LOG_FILE", "logs/bot.log")
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    import structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file),
        ],
    )


# ------------------------------------------------------------------ #
# App lifespan
# ------------------------------------------------------------------ #

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    config = load_config()
    database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./tpt_bot.db")
    engine, session_factory = setup_database(database_url)

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Determine trading mode
    live_gate_env = os.getenv("ENABLE_LIVE_TRADING", "false").lower() == "true"
    live_gate_config = config.get("live_trading", {}).get("live_trading_confirmed", False)
    live_enabled = live_gate_env and live_gate_config
    trading_mode = "LIVE" if live_enabled else "PAPER"

    if live_enabled:
        logger.critical("=" * 60)
        logger.critical("LIVE TRADING MODE ACTIVE — REAL MONEY AT RISK")
        logger.critical("=" * 60)
        from app.execution.tradovate_broker import TradovateBroker
        broker = TradovateBroker()
    else:
        logger.info("PAPER TRADING MODE — no real orders will be placed")
        broker = PaperBroker(session_factory)

    await broker.connect()

    drawdown_tracker = DrawdownTracker(config)
    scheduler = BotScheduler(
        config=config,
        broker=broker,
        drawdown_tracker=drawdown_tracker,
        session_factory=session_factory,
    )

    # Attach to app.state for routes to access
    app.state.config = config
    app.state.db_session_factory = session_factory
    app.state.broker = broker
    app.state.drawdown_tracker = drawdown_tracker
    app.state.scheduler = scheduler
    app.state.trading_mode = trading_mode
    app.state.paused = False
    app.state.last_scan_time = None
    app.state.last_backtest_results = None

    scheduler.start()
    logger.info(f"TPT Future Bot started in {trading_mode} mode")

    yield

    # Shutdown
    scheduler.stop()
    await broker.disconnect()
    await engine.dispose()
    logger.info("TPT Future Bot shut down")


# ------------------------------------------------------------------ #
# FastAPI app
# ------------------------------------------------------------------ #

def create_app() -> FastAPI:
    app = FastAPI(
        title="TPT Future Bot",
        description="Prop-firm-compliant ES/NQ futures trading bot for Take Profit Trader",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Pass request to routes so they can access app.state
    @app.middleware("http")
    async def inject_request(request: Request, call_next):
        response = await call_next(request)
        return response

    app.include_router(router)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "tpt-future-bot"}

    return app


app = create_app()
