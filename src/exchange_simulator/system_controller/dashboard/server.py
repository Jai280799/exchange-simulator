"""FastAPI control plane and live dashboard for a demo session."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    list_data_files,
)
from exchange_simulator.system_controller.controller import SessionController

_logger = logging.getLogger(__name__)

_INDEX = Path(__file__).parent / "static" / "index.html"
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
    strategies: Optional[List[StrategyRequest]] = None


def create_app(
    controller: Optional[SessionController] = None,
    auth_dependency: Optional[Any] = None,
) -> FastAPI:
    session = controller if controller is not None else SessionController()
    guard = auth_dependency if auth_dependency is not None else build_auth_dependency()
    app = FastAPI(
        title="Exchange Simulator",
        version="1.0",
        dependencies=[Depends(guard)],
    )
    app.state.controller = session

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _INDEX.read_text()

    @app.get("/api/options")
    def options() -> Dict[str, Any]:
        return {
            "data_files": list_data_files(),
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

        config = SessionConfig(
            data_path=data_path,
            instrument_id=request.instrument_id,
            date=request.date or None,
            replay_interval_seconds=request.replay_interval_seconds,
            strategies=strategies,
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
