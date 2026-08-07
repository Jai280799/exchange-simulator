"""FastAPI control plane and live dashboard for a demo session."""

import asyncio
import os
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from exchange_simulator.instruments.loader import load_instruments
from exchange_simulator.system_controller.dashboard.auth import build_auth_dependency
from exchange_simulator.strategies.library import STRATEGY_REGISTRY
from exchange_simulator.system_controller.config import (
    DEFAULT_STRATEGIES,
    SessionConfig,
    StrategyConfig,
    default_data_path,
    describe_data_files,
)
from exchange_simulator.system_controller.controller import SessionController

_logger = logging.getLogger(__name__)

_INDEX = Path(__file__).parent / "static" / "index.html"
LOG_FILE_NAME = "system.log"
LOG_TAIL_BYTES = 256 * 1024

STREAM_INTERVAL_SECONDS = 1.0


class StrategyRequest(BaseModel):
    strategy_id: str
    kind: str
    enabled: bool = True


class StartRequest(BaseModel):
    data_path: Optional[str] = None
    instrument_id: str = "2603"
    date: Optional[str] = "2021-08-02"
    replay_interval_seconds: float = 0.002
    # Left unset these follow the SessionConfig defaults rather than shadowing
    # them, so the realism extensions are not silently switched off by the UI.
    market_impact_ticks_per_level: Optional[int] = None
    queue_turnover: Optional[bool] = None
    strategies: Optional[List[StrategyRequest]] = None


def create_app(
    controller: Optional[SessionController] = None,
    auth_dependency: Optional[Any] = None,
) -> FastAPI:
    session = controller if controller is not None else SessionController()
    guard = auth_dependency if auth_dependency is not None else build_auth_dependency()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        # Interrupting uvicorn must not orphan component processes.
        await asyncio.to_thread(session.shutdown)

    app = FastAPI(
        title="Exchange Simulator",
        version="1.0",
        dependencies=[Depends(guard)],
        lifespan=lifespan,
    )
    app.state.controller = session

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        # The page is read from disk on every request, so a browser holding an
        # older copy is the only way to see stale UI. Refuse to be cached.
        return HTMLResponse(_INDEX.read_text(), headers={"Cache-Control": "no-store, must-revalidate"})

    @app.get("/api/options")
    def options() -> Dict[str, Any]:
        return {
            "data_files": describe_data_files(),
            "default_data_path": default_data_path(),
            "instruments": sorted(load_instruments()),
            "strategy_kinds": sorted(STRATEGY_REGISTRY),
            "default_strategies": [
                {"strategy_id": s.strategy_id, "kind": s.kind, "enabled": s.enabled}
                for s in DEFAULT_STRATEGIES
            ],
        }

    @app.get("/api/session")
    def read_session() -> Dict[str, Any]:
        return session.snapshot()

    @app.post("/api/session/start")
    def start_session(request: StartRequest) -> Dict[str, Any]:
        data_path = request.data_path or default_data_path()
        if not data_path:
            raise HTTPException(status_code=400, detail="No market-data file found under var/")

        strategies = (
            tuple(StrategyConfig(s.strategy_id, s.kind, s.enabled) for s in request.strategies)
            if request.strategies
            else DEFAULT_STRATEGIES
        )

        realism: Dict[str, Any] = {}
        if request.market_impact_ticks_per_level is not None:
            realism["market_impact_ticks_per_level"] = request.market_impact_ticks_per_level
        if request.queue_turnover is not None:
            realism["queue_turnover"] = request.queue_turnover

        config = SessionConfig(
            data_path=data_path,
            instrument_id=request.instrument_id,
            date=request.date or None,
            replay_interval_seconds=request.replay_interval_seconds,
            strategies=strategies,
            **realism,
        )

        try:
            run_id = session.start(config)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {"run_id": run_id, "state": str(session.state)}

    @app.post("/api/session/stop")
    def stop_session() -> Dict[str, Any]:
        session.stop()
        return {"state": str(session.state)}

    @app.post("/api/session/pause")
    def pause_session() -> Dict[str, Any]:
        session.pause()
        return {"state": str(session.state), "paused": session.paused}

    @app.post("/api/session/resume")
    def resume_session() -> Dict[str, Any]:
        session.resume()
        return {"state": str(session.state), "paused": session.paused}

    @app.get("/api/logs")
    def read_logs(limit: int = 200, contains: Optional[str] = None) -> Dict[str, Any]:
        """The tail of the running session's log, for the dashboard's Log tab.

        Reads only the last slice of the file so a full trading day stays cheap
        to poll, and drops the first line of that slice because it is usually cut
        mid-message.
        """
        output_dir = session.snapshot().get("output_dir")
        if not output_dir:
            return {"path": None, "lines": []}

        path = Path(output_dir) / LOG_FILE_NAME
        if not path.exists():
            return {"path": str(path), "lines": []}

        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - LOG_TAIL_BYTES))
            block = handle.read().decode("utf-8", errors="replace")

        lines = block.splitlines()
        if size > LOG_TAIL_BYTES and lines:
            lines = lines[1:]
        if contains:
            needle = contains.lower()
            lines = [line for line in lines if needle in line.lower()]

        return {"path": str(path), "lines": lines[-max(1, min(limit, 2000)):]}

    @app.get("/api/stream")
    async def stream() -> StreamingResponse:
        async def events():
            while True:
                payload = await asyncio.to_thread(session.snapshot)
                yield f"data: {json.dumps(payload)}\n\n"
                await asyncio.sleep(STREAM_INTERVAL_SECONDS)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


app = create_app()
