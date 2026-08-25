"""RBAC 初始化 / 数据归集脚本。

用途
----
1. 建 RBAC 表（若未建）并写入内置菜单、内置角色（超级管理员 / 普通用户）；
2. 创建或更新指定账号（默认 ``yankai``，默认绑定「普通用户」角色）；
3. 把库内**所有存量业务数据**（所有含 ``owner_id`` / ``created_by_id`` 的表）
   归属到该账号；
4. 为其他没有角色的存量用户补角色（``users.role=admin`` → 超级管理员，
   其余 → 普通用户）。

用法
----
```bash
cd backend
# 建员工账号 yankai（普通用户）+ 把存量数据全归给它，密码随机生成并打印一次
python -m scripts.rbac_bootstrap --username yankai --random-password
# 指定密码
python -m scripts.rbac_bootstrap --username yankai --password 'xxxxxx'
# 只归集数据，不改密码
python -m scripts.rbac_bootstrap --username yankai --claim-only
# 先看会改哪些表，不落库
python -m scripts.rbac_bootstrap --username yankai --claim-only --dry-run
# 建/重置一个超级管理员（不归集数据）
python -m scripts.rbac_bootstrap --username admin --role admin --random-password --no-claim
# 把误建成超管的账号降回普通用户
python -m scripts.rbac_bootstrap --username yankai --role user --claim-only
```
"""
from __future__ import annotations

import argparse
import secrets
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.rbac import DEFAULT_USER_ROLE_CODE, SUPER_ADMIN_ROLE_CODE  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.init_db import create_all  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.models.rbac import Role  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.services import rbac_service  # noqa: E402

OWNER_COLUMNS = ("owner_id", "created_by_id")
#: RBAC 自身的表不参与归集
SKIP_TABLES = {"users", "roles", "menus", "role_menus", "user_roles", "alembic_version"}


def generate_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def ensure_user(
    db: Session, username: str, password: str | None, *, role_kind: str | None
) -> tuple[User, str | None]:
    """创建/修正账号并绑定内置角色，返回（账号, 本次实际设置的密码）。

    ``role_kind`` 为 ``None`` 时不动已有账号的身份（新建账号按普通用户）；
    显式传 ``user`` / ``admin`` 时以它为准，包括把误建成超管的账号降回普通用户。
    """
    is_admin = role_kind == "admin"
    super_role = db.query(Role).filter(Role.code == SUPER_ADMIN_ROLE_CODE).one()
    normal_role = db.query(Role).filter(Role.code == DEFAULT_USER_ROLE_CODE).one()
    role = super_role if is_admin else normal_role
    legacy_role = UserRole.admin if is_admin else UserRole.user
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        # 新建账号必须有密码：未指定时自动随机生成并在末尾打印
        password = password or generate_password()
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=legacy_role,
            is_active=True,
        )
        db.add(user)
        print(f"[user] 创建账号 {username}（{role.name}）")
    else:
        if password:
            user.password_hash = hash_password(password)
            print(f"[user] 重设 {username} 密码")
        user.is_active = True
        if role_kind is not None:
            user.role = legacy_role
            if not is_admin and super_role in user.roles:
                user.roles = [r for r in user.roles if r is not super_role]
                print(f"[user] {username} 已去除『{super_role.name}』身份")
    if role not in user.roles:
        user.roles = list(user.roles) + [role]
        print(f"[user] {username} 绑定角色『{role.name}』")
    db.commit()
    return user, password


def claim_all_data(db: Session, user: User, dry_run: bool = False) -> dict[str, int]:
    """把所有业务表的归属列指向 ``user``。"""
    insp = inspect(engine)
    changed: dict[str, int] = {}
    for table in insp.get_table_names():
        if table in SKIP_TABLES:
            continue
        cols = {c["name"] for c in insp.get_columns(table)}
        for owner_col in OWNER_COLUMNS:
            if owner_col not in cols:
                continue
            # 含 NULL 的历史行也一并归集，否则它们在私有模块里会永远看不到
            where = f"`{owner_col}` IS NULL OR `{owner_col}` <> :uid"
            count = db.execute(
                text(f"SELECT COUNT(*) FROM `{table}` WHERE {where}"),
                {"uid": user.id},
            ).scalar_one()
            key = f"{table}.{owner_col}"
            changed[key] = int(count or 0)
            if count and not dry_run:
                db.execute(
                    text(f"UPDATE `{table}` SET `{owner_col}` = :uid WHERE {where}"),
                    {"uid": user.id},
                )
    if not dry_run:
        db.commit()
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="RBAC 初始化 / 数据归集")
    parser.add_argument("--username", default="yankai", help="目标账号登录名")
    parser.add_argument(
        "--role",
        choices=("user", "admin"),
        default=None,
        help=(
            "显式指定该账号的身份（user=普通用户、admin=超级管理员），"
            "会覆盖现有身份；不传则不动已有账号的身份，新建账号按普通用户"
        ),
    )
    parser.add_argument("--password", default=None, help="指定密码")
    parser.add_argument(
        "--random-password", action="store_true", help="随机生成密码并打印"
    )
    parser.add_argument(
        "--claim-only", action="store_true", help="不改密码，只做菜单初始化 + 数据归集"
    )
    parser.add_argument(
        "--no-claim", action="store_true", help="只初始化 RBAC 和账号，不归集数据"
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印将要变更的行数")
    args = parser.parse_args()

    password: str | None = args.password
    if args.random_password:
        password = generate_password()
    if args.claim_only:
        password = None

    create_all()
    with SessionLocal() as db:
        rbac_service.seed_rbac(db)
        print("[rbac] 内置菜单 / 角色已就绪")
        user, password = ensure_user(db, args.username, password, role_kind=args.role)
        rbac_service.sync_legacy_admin_roles(db)
        print(
            f"[rbac] 其他存量用户已补齐角色（默认『{DEFAULT_USER_ROLE_CODE}』）"
        )

        if not args.no_claim:
            changed = claim_all_data(db, user, dry_run=args.dry_run)
            total = sum(changed.values())
            for key, count in sorted(changed.items()):
                if count:
                    print(f"[claim] {key}: {count} 行 -> user_id={user.id}")
            prefix = "将要迁移" if args.dry_run else "已迁移"
            print(f"[claim] {prefix} {total} 行数据到 {user.username}(id={user.id})")

    if password:
        print("=" * 56)
        print(f"账号: {args.username}")
        print(f"密码: {password}")
        print("请立即保存，此密码不会再次显示。")
        print("=" * 56)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
