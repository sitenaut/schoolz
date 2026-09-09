from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

import auth as auth_module
from auth import get_current_user, hash_password, verify_password, create_local_token
from database import get_db
from models import User
from schemas import RegisterRequest, LoginRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    if auth_module.AUTH_MODE != "local":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    existing = await db.execute(
        select(User).where(or_(User.email == payload.email, User.username == payload.username))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "Email or username already registered")

    user = User(
        email=payload.email,
        username=payload.username,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return TokenResponse(access_token=create_local_token(user.id))


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    if auth_module.AUTH_MODE != "local":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    result = await db.execute(
        select(User).where(
            or_(User.email == payload.username_or_email, User.username == payload.username_or_email)
        )
    )
    user = result.scalar_one_or_none()
    if not user or not user.password_hash or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect username/email or password")

    return TokenResponse(access_token=create_local_token(user.id))


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return UserOut(
        id=user.id,
        email=user.email,
        username=user.username,
        is_admin=user.is_admin,
        auth_mode=auth_module.AUTH_MODE,
    )
