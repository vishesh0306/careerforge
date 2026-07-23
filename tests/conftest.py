import pytest
from sqlalchemy.orm import Session

from app.core.db import engine


@pytest.fixture()
def db_session() -> Session:
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
