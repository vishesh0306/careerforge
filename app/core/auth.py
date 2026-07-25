from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import InvalidTokenError, decode_access_token
from app.models import User

bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme), db: Session = Depends(get_db)
) -> User:
    try:
        user_id = decode_access_token(credentials.credentials)
    except InvalidTokenError as exc:
        # Deliberately don't include str(exc) — it can echo raw decode-library internals
        # (encoding errors, etc.) back to the client for no benefit.
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User for this token no longer exists")
    return user
