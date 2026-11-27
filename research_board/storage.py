import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from research_board.board import InvalidAction, apply_operation
from research_board.models import ActionRequest, Board, Decision, Operation, StateEnvelope

CRITICAL_ACTIONS = frozenset({"delete_claim", "bulk_delete_links", "export"})
operation_adapter = TypeAdapter(Operation)


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class BoardStore:
    """Local SQLite adapter. Each write reserves the lock before reading the current version."""

    def __init__(self, path: str | Path):
        self.path = path
        with closing(self._connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS versions (
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    state_version INTEGER NOT NULL,
                    envelope TEXT NOT NULL,
                    PRIMARY KEY (session_id, state_version)
                );
                CREATE TABLE IF NOT EXISTS confirmations (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    expected_version INTEGER NOT NULL,
                    operation TEXT NOT NULL,
                    status TEXT NOT NULL,
                    FOREIGN KEY (session_id, expected_version)
                        REFERENCES versions(session_id, state_version)
                );
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY,
                    confirmation_id TEXT NOT NULL REFERENCES confirmations(id),
                    event TEXT NOT NULL,
                    state_version INTEGER NOT NULL,
                    timestamp TEXT NOT NULL
                );
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    @contextmanager
    def _write(self):
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    def _read_state(self, db: sqlite3.Connection, session_id: str, version: int | None = None):
        if version is None:
            row = db.execute(
                "SELECT envelope FROM versions WHERE session_id = ? ORDER BY state_version DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        else:
            row = db.execute(
                "SELECT envelope FROM versions WHERE session_id = ? AND state_version = ?",
                (session_id, version),
            ).fetchone()
        if row is None:
            raise NotFound("Session or state version not found")
        return StateEnvelope.model_validate_json(row["envelope"])

    def _save(self, db: sqlite3.Connection, session_id: str, version: int, board: Board):
        state = StateEnvelope(
            session_id=session_id, state_version=version, payload=board, updated_at=datetime.now(UTC),
        )
        db.execute("INSERT INTO versions VALUES (?, ?, ?)", (session_id, version, state.model_dump_json()))
        return state

    def create(self, conversation_id: str, actor_id: str, board: Board) -> StateEnvelope:
        session_id = str(uuid4())
        with self._write() as db:
            db.execute("INSERT INTO sessions VALUES (?, ?, ?)", (session_id, conversation_id, actor_id))
            return self._save(db, session_id, 1, board)

    def get(self, session_id: str, version: int | None = None) -> tuple[StateEnvelope, str]:
        with closing(self._connect()) as db:
            state = self._read_state(db, session_id, version)
            session = db.execute("SELECT conversation_id FROM sessions WHERE id = ?", (session_id,)).fetchone()
            return state, session["conversation_id"]

    def _record(self, db: sqlite3.Connection, confirmation_id: str, event: str, version: int):
        db.execute(
            "INSERT INTO audit (confirmation_id, event, state_version, timestamp) VALUES (?, ?, ?, ?)",
            (confirmation_id, event, version, datetime.now(UTC).isoformat()),
        )

    def _updated_board(self, state: StateEnvelope, operation: Operation) -> Board:
        if operation.action == "export":
            return state.payload
        try:
            return apply_operation(state.payload, operation)
        except ValidationError as exc:
            raise InvalidAction(exc.errors(include_input=False, include_url=False)[0]["msg"]) from exc

    def apply(self, session_id: str, request: ActionRequest) -> tuple[StateEnvelope, dict | None]:
        with self._write() as db:
            state = self._read_state(db, session_id)
            if request.expected_version != state.state_version:
                raise Conflict("State version changed. Load the current state and retry.")
            operation = request.operation
            board = self._updated_board(state, operation)
            if operation.action not in CRITICAL_ACTIONS:
                return self._save(db, session_id, state.state_version + 1, board), None

            confirmation_id = str(uuid4())
            db.execute(
                "INSERT INTO confirmations VALUES (?, ?, ?, ?, 'pending')",
                (confirmation_id, session_id, state.state_version, operation.model_dump_json()),
            )
            self._record(db, confirmation_id, "requested", state.state_version)
            return state, {
                "id": confirmation_id,
                "status": "pending",
                "expected_version": state.state_version,
                "operation": operation.model_dump(mode="json"),
            }

    def decide(self, session_id: str, confirmation_id: str, request: Decision) -> tuple[StateEnvelope, dict]:
        with self._write() as db:
            state = self._read_state(db, session_id)
            row = db.execute(
                "SELECT * FROM confirmations WHERE id = ? AND session_id = ?",
                (confirmation_id, session_id),
            ).fetchone()
            if row is None:
                raise NotFound("Confirmation not found")
            if row["status"] != "pending":
                raise Conflict("Confirmation was already decided")

            operation = operation_adapter.validate_json(row["operation"])
            expected_version = row["expected_version"]
            result = {"id": confirmation_id, "operation": operation.model_dump(mode="json")}
            if request.decision == "reject":
                outcome = "rejected"
                self._record(db, confirmation_id, outcome, expected_version)
            elif expected_version != state.state_version:
                outcome = "stale"
                self._record(db, confirmation_id, outcome, state.state_version)
            else:
                outcome = "executed"
                self._record(db, confirmation_id, "approved", expected_version)
                if operation.action == "export":
                    result["export"] = state.model_dump(mode="json")
                else:
                    board = self._updated_board(state, operation)
                    state = self._save(db, session_id, state.state_version + 1, board)
                self._record(db, confirmation_id, outcome, state.state_version)
            db.execute("UPDATE confirmations SET status = ? WHERE id = ?", (outcome, confirmation_id))

        if outcome == "stale":
            raise Conflict("State version changed after the confirmation request. Request a new confirmation.")
        result["status"] = outcome
        return state, result

    def audit(self, session_id: str) -> list[dict]:
        with closing(self._connect()) as db:
            session = db.execute(
                "SELECT conversation_id, actor_id FROM sessions WHERE id = ?", (session_id,),
            ).fetchone()
            if session is None:
                raise NotFound("Session not found")
            events = db.execute("""
                SELECT audit.id, audit.event, audit.state_version, audit.timestamp,
                    confirmation_id, confirmations.expected_version, confirmations.operation
                FROM audit JOIN confirmations ON confirmations.id = audit.confirmation_id
                WHERE confirmations.session_id = ?
                ORDER BY audit.id
            """, (session_id,)).fetchall()
            return [
                {
                    **dict(session),
                    **dict(row),
                    "session_id": session_id,
                    "operation": json.loads(row["operation"]),
                }
                for row in events
            ]
