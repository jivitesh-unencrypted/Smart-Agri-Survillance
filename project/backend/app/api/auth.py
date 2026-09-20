import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])

_USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]+$")


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    """
    Open self-registration - any user can create their own account and
    is signed in immediately, with no admin approval step. Every
    account created this way has equal (standard "user") access to the
    app; there is no separate admin role gating any feature.
    """
    username = payload.username.strip()

    if not _USERNAME_PATTERN.match(username):
        raise HTTPException(
            status_code=422,
            detail="Username can only contain letters, numbers, dots, underscores, and hyphens.",
        )
    if payload.password != payload.confirm_password:
        raise HTTPException(status_code=422, detail="Passwords do not match.")

    existing = db.query(User).filter(User.username == username).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="That username is already taken.")

    user = User(
        username=username,
        hashed_password=hash_password(payload.password),
        role="user",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(subject=user.username)
    return TokenResponse(access_token=token, username=user.username, role=user.role)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    token = create_access_token(subject=user.username)
    return TokenResponse(access_token=token, username=user.username, role=user.role)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user
