import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request

from explorer.analysis import InvalidConfiguration
from explorer.dataset import InvalidDataset, MAX_BYTES, parse_dataset
from explorer.models import Configuration, SaveState
from explorer.storage import Conflict, ExplorerStore, NotFound
from explorer.ui import make_ui_schema


def create_app(db_path=None, store_factory=None):
    @asynccontextmanager
    async def lifespan(app):
        if store_factory is not None:
            app.state.store = store_factory()
        elif db_path is not None:
            app.state.store = ExplorerStore(db_path)
        elif os.getenv('EXPLORER_DATABASE_URL'):
            from explorer.postgres_storage import PostgresExplorerStore
            app.state.store = PostgresExplorerStore(os.environ['EXPLORER_DATABASE_URL'], schema=os.getenv('EXPLORER_DATABASE_SCHEMA', 'public'))
        else:
            app.state.store = ExplorerStore(db_path or os.getenv('EXPLORER_DB', 'explorer.db'))
        yield

    app = FastAPI(title='Data Explorer API', version='1.0.0', lifespan=lifespan)

    def view(state):
        dataset = state.pop('dataset')
        config = Configuration.model_validate(state['payload']['configuration'])
        return {'state': state, 'data': {'columns': dataset['columns'], 'rows': dataset['rows']},
                'ui_schema': make_ui_schema(dataset, config, state['payload']['aggregates'])}

    @app.post('/api/data-explorer/sessions', status_code=201)
    async def create(request: Request, filename: str = Query(min_length=1, max_length=255)):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_BYTES:
                raise HTTPException(413, 'Размер файла превышает 1 000 000 байт')
        try:
            dataset = parse_dataset(filename, bytes(raw))
            return view(request.app.state.store.create(Path(filename).name, bytes(raw), dataset))
        except (InvalidDataset, InvalidConfiguration) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get('/api/data-explorer/sessions/{session_id}')
    def get(request: Request, session_id: str, version: int | None = Query(default=None, ge=1)):
        try:
            return view(request.app.state.store.get(session_id, version))
        except NotFound as exc:
            raise HTTPException(404, 'Сессия или версия не найдена') from exc

    @app.put('/api/data-explorer/sessions/{session_id}')
    def save(request: Request, session_id: str, update: SaveState):
        try:
            return view(request.app.state.store.save(session_id, update.expected_version, update.configuration))
        except NotFound as exc:
            raise HTTPException(404, 'Сессия не найдена') from exc
        except Conflict as exc:
            raise HTTPException(409, 'Версия состояния изменилась; загрузите актуальную версию') from exc
        except InvalidConfiguration as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get('/api/data-explorer/sessions/{session_id}/handoff')
    def handoff(request: Request, session_id: str, version: int | None = Query(default=None, ge=1)):
        try:
            state = request.app.state.store.get(session_id, version)
            state.pop('dataset')
            return state
        except NotFound as exc:
            raise HTTPException(404, 'Сессия или версия не найдена') from exc

    return app


app = create_app()
