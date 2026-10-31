import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

class Base(DeclarativeBase): pass

url = os.getenv('DATABASE_URL', 'sqlite:///./writer.db')
if url.startswith('postgres://'): url='postgresql+psycopg://' + url[len('postgres://'):]
if url.startswith('postgresql://'): url='postgresql+psycopg://' + url[len('postgresql://'):]
is_sqlite=url.startswith('sqlite:')
engine=create_engine(url, pool_pre_ping=True, connect_args={'check_same_thread':False, 'timeout':30} if is_sqlite else {})
if is_sqlite:
    @event.listens_for(engine, 'connect')
    def sqlite_config(conn,_):
        c=conn.cursor(); c.execute('PRAGMA foreign_keys=ON'); c.execute('PRAGMA busy_timeout=30000'); c.close()
SessionLocal=sessionmaker(bind=engine, expire_on_commit=False)

def get_db():
    with SessionLocal() as db: yield db
