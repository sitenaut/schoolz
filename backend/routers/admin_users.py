from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_super_admin
from database import get_db
from models import Role, RolePermission, User, UserRole
from permissions import PERMISSION_KEYS, PERMISSIONS

router = APIRouter(prefix="/admin", tags=["admin-users"], dependencies=[Depends(require_super_admin)])


class PermissionOut(BaseModel):
    key: str
    label: str
    description: str
    sensitive: bool
    access: str


class RoleIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=255)
    permissions: list[str] = []

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name is required")
        return v

    @field_validator("permissions")
    @classmethod
    def _known(cls, v: list[str]) -> list[str]:
        unknown = sorted(set(v) - PERMISSION_KEYS)
        if unknown:
            raise ValueError(f"Unknown permission: {', '.join(unknown)}")
        return sorted(set(v))


class RoleOut(BaseModel):
    id: str
    name: str
    description: str | None
    permissions: list[str]
    user_count: int


class AdminUserOut(BaseModel):
    id: str
    email: str
    username: str
    is_admin: bool
    role_ids: list[str]
    created_at: str | None


class UsersPageOut(BaseModel):
    items: list[AdminUserOut]
    total: int


class UserRolesIn(BaseModel):
    role_ids: list[str]


class SuperAdminIn(BaseModel):
    is_admin: bool


@router.get("/permissions", response_model=list[PermissionOut])
async def list_permissions():
    return [PermissionOut(key=p.key, label=p.label, description=p.description, sensitive=p.sensitive, access=p.access) for p in PERMISSIONS]


async def _role_out(db: AsyncSession, role: Role) -> RoleOut:
    perms = (await db.execute(select(RolePermission.permission).where(RolePermission.role_id == role.id))).scalars().all()
    count = (await db.execute(select(func.count()).select_from(UserRole).where(UserRole.role_id == role.id))).scalar_one()
    return RoleOut(id=role.id, name=role.name, description=role.description, permissions=sorted(perms), user_count=count)


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(db: AsyncSession = Depends(get_db)):
    roles = (await db.execute(select(Role).order_by(Role.name))).scalars().all()
    return [await _role_out(db, r) for r in roles]


async def _name_taken(db: AsyncSession, name: str, except_id: str | None = None) -> bool:
    q = select(Role.id).where(func.lower(Role.name) == name.lower())
    if except_id:
        q = q.where(Role.id != except_id)
    return (await db.execute(q)).first() is not None


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
async def create_role(payload: RoleIn, db: AsyncSession = Depends(get_db)):
    if await _name_taken(db, payload.name):
        raise HTTPException(status.HTTP_409_CONFLICT, "A role with that name already exists")
    role = Role(name=payload.name, description=payload.description)
    db.add(role)
    await db.flush()
    db.add_all(RolePermission(role_id=role.id, permission=p) for p in payload.permissions)
    await db.commit()
    return await _role_out(db, role)


async def _get_role(db: AsyncSession, role_id: str) -> Role:
    role = (await db.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
    if not role:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    return role


@router.put("/roles/{role_id}", response_model=RoleOut)
async def update_role(role_id: str, payload: RoleIn, db: AsyncSession = Depends(get_db)):
    role = await _get_role(db, role_id)
    if await _name_taken(db, payload.name, except_id=role.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "A role with that name already exists")
    role.name = payload.name
    role.description = payload.description
    await db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
    db.add_all(RolePermission(role_id=role.id, permission=p) for p in payload.permissions)
    await db.commit()
    return await _role_out(db, role)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(role_id: str, db: AsyncSession = Depends(get_db)):
    role = await _get_role(db, role_id)
    await db.delete(role)
    await db.commit()


async def _user_out(db: AsyncSession, users: list[User]) -> list[AdminUserOut]:
    ids = [u.id for u in users]
    by_user: dict[str, list[str]] = {i: [] for i in ids}
    if ids:
        rows = (await db.execute(select(UserRole.user_id, UserRole.role_id).where(UserRole.user_id.in_(ids)))).all()
        for uid, rid in rows:
            by_user[uid].append(rid)
    return [
        AdminUserOut(
            id=u.id,
            email=u.email,
            username=u.username,
            is_admin=u.is_admin,
            role_ids=sorted(by_user[u.id]),
            created_at=u.created_at.isoformat() if u.created_at else None,
        )
        for u in users
    ]


@router.get("/users", response_model=UsersPageOut)
async def list_users(
    q: str | None = None,
    admins_only: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    query = select(User)
    if q and q.strip():
        for token in q.split():
            like = f"%{token}%"
            query = query.where(or_(User.email.ilike(like), User.username.ilike(like)))
    if admins_only:
        has_role = select(UserRole.user_id).where(UserRole.user_id == User.id).exists()
        query = query.where(or_(User.is_admin.is_(True), has_role))
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    users = (await db.execute(query.order_by(User.is_admin.desc(), User.email).limit(limit).offset(offset))).scalars().all()
    return UsersPageOut(items=await _user_out(db, list(users)), total=total)


async def _get_user(db: AsyncSession, user_id: str) -> User:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


@router.put("/users/{user_id}/roles", response_model=AdminUserOut)
async def set_user_roles(user_id: str, payload: UserRolesIn, db: AsyncSession = Depends(get_db)):
    user = await _get_user(db, user_id)
    wanted = set(payload.role_ids)
    if wanted:
        found = set((await db.execute(select(Role.id).where(Role.id.in_(wanted)))).scalars().all())
        if found != wanted:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown role")
    await db.execute(delete(UserRole).where(UserRole.user_id == user.id))
    db.add_all(UserRole(user_id=user.id, role_id=r) for r in wanted)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A role was deleted while you were editing; reload and retry")
    return (await _user_out(db, [user]))[0]


@router.put("/users/{user_id}/super-admin", response_model=AdminUserOut)
async def set_super_admin(
    user_id: str,
    payload: SuperAdminIn,
    actor: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user(db, user_id)
    if not payload.is_admin and user.id == actor.id:
        # Only a super admin can reach this route, so refusing self-demotion
        # is what guarantees there is always at least one super admin left.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't remove your own super admin access; ask another super admin")
    user.is_admin = payload.is_admin
    await db.commit()
    return (await _user_out(db, [user]))[0]
