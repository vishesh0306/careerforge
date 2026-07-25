import pytest
from sqlalchemy.orm import Session

from app.core.db import engine
from app.core.security import create_access_token


def auth_headers_for(user_id: int) -> dict:
    """Issues a real access token the same way POST /auth/login does, without needing every test
    to also drive a full register/login HTTP round trip just to get one."""
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


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
