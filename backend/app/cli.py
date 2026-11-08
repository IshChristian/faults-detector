"""Bootstrap accounts. There is no self-registration, so the first accounts come from here.

    python -m app.cli create-super-admin --email E --name N
    python -m app.cli create-customer --name N --industry sports --admin-email E --admin-name N

The password is read from VG_PASSWORD when set (scripts), otherwise prompted for twice.
An email that already exists exits with code 1 and changes nothing.
"""
import argparse
import asyncio
import os
import sys
from getpass import getpass

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.auth.security import hash_password
from app.auth.service import find_user_by_email
from app.models import Customer, User

INDUSTRIES = ("restaurant", "sports", "retail", "factory", "school", "security", "other")
MIN_PASSWORD = 10


class DuplicateEmailError(Exception):
    pass


def read_password() -> str:
    pw = os.environ.get("VG_PASSWORD")
    if pw is None:
        pw = getpass("Password: ")
        if getpass("Repeat password: ") != pw:
            sys.exit("Passwords do not match.")
    if len(pw) < MIN_PASSWORD:
        sys.exit(f"Password must be at least {MIN_PASSWORD} characters.")
    return pw


async def _ensure_new_email(session: AsyncSession, email: str) -> str:
    email = email.strip().lower()
    if await find_user_by_email(session, email):
        raise DuplicateEmailError(f"A user with email {email} already exists.")
    return email


async def create_super_admin(session: AsyncSession, email: str, name: str, password: str) -> User:
    email = await _ensure_new_email(session, email)
    user = User(customer_id=None, email=email, full_name=name, password_hash=hash_password(password),
                role="super_admin")
    session.add(user)
    await session.flush()
    await record_audit(session, action="cli.create_super_admin", customer_id=None, entity_type="user",
                       entity_id=user.id, details={"email": email})
    return user


async def create_customer_with_admin(session: AsyncSession, name: str, industry: str, admin_email: str,
                                     admin_name: str, password: str) -> tuple[Customer, User]:
    email = await _ensure_new_email(session, admin_email)  # checked before anything is written
    customer = Customer(name=name, industry=industry)
    session.add(customer)
    await session.flush()
    admin = User(customer_id=customer.id, email=email, full_name=admin_name,
                 password_hash=hash_password(password), role="customer_admin")
    session.add(admin)
    await session.flush()
    await record_audit(session, action="cli.create_customer", customer_id=customer.id, entity_type="customer",
                       entity_id=customer.id, details={"name": name, "admin_email": email})
    return customer, admin


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.cli", description="VisionGuard bootstrap commands")
    sub = p.add_subparsers(dest="command", required=True)
    sa = sub.add_parser("create-super-admin", help="create the platform owner account")
    sa.add_argument("--email", required=True)
    sa.add_argument("--name", required=True)
    cc = sub.add_parser("create-customer", help="create a customer and its first customer_admin")
    cc.add_argument("--name", required=True)
    cc.add_argument("--industry", required=True, choices=INDUSTRIES)
    cc.add_argument("--admin-email", required=True)
    cc.add_argument("--admin-name", required=True)
    return p


async def _run(args: argparse.Namespace, password: str) -> str:
    from app.db import get_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = get_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            if args.command == "create-super-admin":
                user = await create_super_admin(session, args.email, args.name, password)
                out = f"Created super admin {user.email} ({user.id})"
            else:
                customer, admin = await create_customer_with_admin(
                    session, args.name, args.industry, args.admin_email, args.admin_name, password)
                out = str(customer.id)
            await session.commit()
            return out
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    password = read_password()
    try:
        print(asyncio.run(_run(args, password)))
    except DuplicateEmailError as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
