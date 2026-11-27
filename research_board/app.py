import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse

from research_board.board import InvalidAction, handoff
from research_board.models import (
    APP_VERSION, MAX_STATE_VERSION, ActionRequest, Board, Decision, FixtureInput, Launch, StateEnvelope,
)
from research_board.storage import BoardStore, Conflict, NotFound
from research_board.ui import BoardFilter, ui_schema

router = APIRouter(prefix="/api/research-board/sessions", tags=["Research Board"])
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "research-board"
HistoricalVersion = Annotated[int | None, Query(ge=1, le=MAX_STATE_VERSION)]


def view(state: StateEnvelope, board_filter: BoardFilter = "Все") -> dict:
    return {"state": state.model_dump(mode="json"), "ui_schema": ui_schema(state, board_filter)}


@router.post("", status_code=201)
def launch(request: Request, launch: Launch):
    if isinstance(launch.input, FixtureInput):
        board = Board.model_validate_json((FIXTURES / f"{launch.input.fixture}.json").read_bytes())
    else:
        board = launch.input.board
    return view(request.app.state.research_board_store.create(launch.conversation_id, launch.actor_id, board))


@router.get("/{session_id}")
def get_session(
    request: Request, session_id: str, version: HistoricalVersion = None,
    board_filter: BoardFilter = "Все",
):
    state, _ = request.app.state.research_board_store.get(session_id, version)
    return view(state, board_filter)


@router.post("/{session_id}/actions")
def action(request: Request, response: Response, session_id: str, action: ActionRequest):
    state, confirmation = request.app.state.research_board_store.apply(session_id, action)
    result = view(state)
    if confirmation is not None:
        response.status_code = 202
        result["confirmation"] = confirmation
    return result


@router.post("/{session_id}/confirmations/{confirmation_id}")
def confirm(request: Request, session_id: str, confirmation_id: str, decision: Decision):
    state, confirmation = request.app.state.research_board_store.decide(session_id, confirmation_id, decision)
    return {**view(state), "confirmation": confirmation}


@router.get("/{session_id}/handoff")
def get_handoff(request: Request, session_id: str, version: HistoricalVersion = None):
    state, conversation_id = request.app.state.research_board_store.get(session_id, version)
    return {"state": state.model_dump(mode="json"), **handoff(state, conversation_id)}


@router.get("/{session_id}/audit")
def get_audit(request: Request, session_id: str):
    return {"events": request.app.state.research_board_store.audit(session_id)}


def create_app(db_path: str | Path | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.research_board_store = BoardStore(db_path or os.getenv("RESEARCH_BOARD_DB", "research-board.db"))
        yield

    app = FastAPI(title="Research Board API", version=APP_VERSION, lifespan=lifespan)
    app.include_router(router)

    @app.exception_handler(NotFound)
    async def not_found_handler(request: Request, exc: NotFound):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(Conflict)
    async def conflict_handler(request: Request, exc: Conflict):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(InvalidAction)
    async def invalid_action_handler(request: Request, exc: InvalidAction):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    return app


app = create_app()
