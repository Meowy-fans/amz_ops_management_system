"""数据库连接池"""
import logging
import os
from contextlib import contextmanager
from typing import Optional
from sqlalchemy import create_engine, pool
from sqlalchemy.orm import sessionmaker, Session
from src.config.settings import settings
logger = logging.getLogger(__name__)

class DatabaseManager:
    _instance: Optional["DatabaseManager"] = None
    _engine = None
    _session_factory = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._engine is None:
            # Use Pydantic Settings for URL
            url = settings.DATABASE_URL
            
            self._engine = create_engine(
                url,
                poolclass=pool.QueuePool,
                pool_size=5,
                max_overflow=10,
                pool_timeout=30,
                pool_recycle=3600,
                pool_pre_ping=True,
                echo=False,
            )
            self._session_factory = sessionmaker(
                bind=self._engine,
                autocommit=False,
                autoflush=False,
            )
            logger.info("数据库连接池初始化成功")
    
    def get_session(self) -> Session:
        return self._session_factory()
    
    @contextmanager
    def session_scope(self):
        session = self.get_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

db_manager = DatabaseManager()

def SessionLocal() -> Session:
    return db_manager.get_session()
