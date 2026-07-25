from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings

JWT_SUBJECT_CLAIM = "sub"


class InvalidTokenError(Exception):
    """Raised when a bearer token is missing, malformed, expired, or signed with a different key."""


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(user_id: int) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {JWT_SUBJECT_CLAIM: str(user_id), "exp": expires_at}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> int:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc

    subject = payload.get(JWT_SUBJECT_CLAIM)
    if subject is None:
        raise InvalidTokenError("Token is missing its subject claim")
    try:
        return int(subject)
    except ValueError as exc:
        raise InvalidTokenError("Token subject is not a valid user id") from exc
