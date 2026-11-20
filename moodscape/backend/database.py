import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# 默认 SQLite 开发库；设置 MOODSCAPE_DB_URL 可切换到独立测试库或 PostgreSQL。
SQLALCHEMY_DATABASE_URL = os.getenv("MOODSCAPE_DB_URL", "sqlite:///./moodscape.db")

connect_args = {"check_same_thread": False} if SQLALCHEMY_DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
