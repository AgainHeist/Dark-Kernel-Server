from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import get_settings

class Base(DeclarativeBase): pass
url = get_settings().database_url
if url.startswith('sqlite:///') and ':memory:' not in url:
    Path(url.removeprefix('sqlite:///')).parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(url, pool_pre_ping=True, connect_args={'check_same_thread':False, 'timeout':20} if url.startswith('sqlite:') else {})
if url.startswith('sqlite:'):
    @event.listens_for(engine, 'connect')
    def setup_sqlite(conn, _):
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA journal_mode=WAL')
SessionLocal = sessionmaker(engine, expire_on_commit=False)

def get_db():
    with SessionLocal() as db:
        try:
            # SQLite local development serializes request transactions; MySQL uses row locks.
            if engine.dialect.name == 'sqlite': db.connection().exec_driver_sql('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
