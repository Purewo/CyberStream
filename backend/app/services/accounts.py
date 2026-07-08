from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar

from flask import current_app, g, has_request_context
from sqlalchemy import event, inspect as sa_inspect
from sqlalchemy.orm import Session, with_loader_criteria

from backend.app.extensions import db
from backend.app.models import (
    ACCOUNT_SCOPED_MODELS,
    Account,
    AccountMembership,
    HomepageSetting,
    Library,
)


_BACKGROUND_ACCOUNT_ID = ContextVar("cyberstream_account_id", default=None)
_SESSION_HOOKS_INSTALLED = False
_ACCOUNT_SCOPED_MODEL_SET = set(ACCOUNT_SCOPED_MODELS)


def current_account_id():
    if has_request_context():
        request_account_id = getattr(g, "current_account_id", None)
        if request_account_id:
            return request_account_id
    return _BACKGROUND_ACCOUNT_ID.get()


def is_account_scoped_model(model):
    return model in _ACCOUNT_SCOPED_MODEL_SET


def get_account_scoped(model, ident):
    account_id = current_account_id()
    if not account_id or not is_account_scoped_model(model):
        return db.session.get(model, ident)

    primary_keys = sa_inspect(model).primary_key
    query = db.session.query(model).filter(model.account_id == account_id)
    if len(primary_keys) == 1:
        return query.filter(primary_keys[0] == ident).first()

    if isinstance(ident, dict):
        values = [ident.get(column.key, ident.get(column.name)) for column in primary_keys]
    elif isinstance(ident, (tuple, list)):
        values = list(ident)
    else:
        return None
    if len(values) != len(primary_keys) or any(value is None for value in values):
        return None
    for column, value in zip(primary_keys, values):
        query = query.filter(column == value)
    return query.first()


def set_request_account(membership=None):
    if not has_request_context():
        return
    account = membership.account if membership else None
    g.current_account_membership = membership
    g.current_account = account
    g.current_account_id = account.id if account else None
    g.current_account_role = membership.role if membership else None


@contextmanager
def account_scope(account_id):
    token = _BACKGROUND_ACCOUNT_ID.set(str(account_id) if account_id else None)
    try:
        yield
    finally:
        _BACKGROUND_ACCOUNT_ID.reset(token)


def _normalize_slug(value):
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return slug[:80] or "account"


def _available_account_slug(value):
    base = _normalize_slug(value)
    candidate = base
    suffix = 2
    while Account.query.execution_options(include_all_accounts=True).filter_by(slug=candidate).first():
        candidate = f"{base[:72]}-{suffix}"
        suffix += 1
    return candidate


def _default_library_slug():
    return _normalize_slug(current_app.config.get("DEFAULT_ACCOUNT_LIBRARY_SLUG") or "default")


def _default_homepage_sections():
    return [
        {"key": "sci_fi", "title": "科幻", "genre": "科幻", "mode": "latest", "limit": 15, "movie_ids": [], "enabled": True, "sort_order": 0},
        {"key": "action", "title": "动作", "genre": "动作", "mode": "latest", "limit": 15, "movie_ids": [], "enabled": True, "sort_order": 1},
        {"key": "drama", "title": "剧情", "genre": "剧情", "mode": "latest", "limit": 15, "movie_ids": [], "enabled": True, "sort_order": 2},
        {"key": "animation", "title": "动画", "genre": "动画", "mode": "latest", "limit": 15, "movie_ids": [], "enabled": True, "sort_order": 3},
    ]


def _create_default_library(account):
    library = Library(
        account_id=account.id,
        name=str(current_app.config.get("DEFAULT_ACCOUNT_LIBRARY_NAME") or "默认片库").strip() or "默认片库",
        slug=_default_library_slug(),
        settings={},
    )
    db.session.add(library)
    db.session.flush()
    return library


def backfill_legacy_account_data(account_id):
    """Assign pre-tenant rows to the designated legacy owner account."""
    updated = {}
    for model in ACCOUNT_SCOPED_MODELS:
        if model is AccountMembership:
            continue
        count = (
            model.query.execution_options(include_all_accounts=True)
            .filter(model.account_id.is_(None))
            .update({model.account_id: account_id}, synchronize_session=False)
        )
        if count:
            updated[model.__tablename__] = int(count)
    return updated


def create_account_for_user(
    user,
    *,
    account_name=None,
    account_slug=None,
    adopt_legacy_data=False,
):
    if not user.id:
        db.session.flush()

    existing = (
        AccountMembership.query.execution_options(include_all_accounts=True)
        .filter_by(user_id=user.id, status=AccountMembership.STATUS_ACTIVE)
        .order_by(AccountMembership.id.asc())
        .first()
    )
    if existing:
        return existing

    account = Account(
        name=str(account_name or user.display_name or user.username).strip() or user.username,
        slug=_available_account_slug(account_slug or user.username),
        status=Account.STATUS_ACTIVE,
        settings={},
    )
    db.session.add(account)
    db.session.flush()

    membership = AccountMembership(
        account_id=account.id,
        user_id=user.id,
        role=AccountMembership.ROLE_OWNER,
        status=AccountMembership.STATUS_ACTIVE,
    )
    db.session.add(membership)
    db.session.flush()

    migrated = backfill_legacy_account_data(account.id) if adopt_legacy_data else {}
    default_library = (
        Library.query.execution_options(include_all_accounts=True)
        .filter_by(account_id=account.id)
        .order_by(Library.sort_order.asc(), Library.id.asc())
        .first()
    )
    if not default_library:
        default_library = _create_default_library(account)

    if not current_app.config.get("HOSTED_MANAGED_MODE"):
        homepage = (
            HomepageSetting.query.execution_options(include_all_accounts=True)
            .filter_by(account_id=account.id)
            .first()
        )
        if not homepage:
            db.session.add(HomepageSetting(account_id=account.id, sections=_default_homepage_sections()))

    account.settings = {
        **(account.settings or {}),
        "default_library_id": default_library.id,
        "legacy_rows_adopted": migrated,
    }
    return membership


def active_membership_for_user(user):
    if not user or not user.id:
        return None
    return (
        AccountMembership.query.execution_options(include_all_accounts=True)
        .join(Account, Account.id == AccountMembership.account_id)
        .filter(
            AccountMembership.user_id == user.id,
            AccountMembership.status == AccountMembership.STATUS_ACTIVE,
            Account.status == Account.STATUS_ACTIVE,
        )
        .order_by(
            db.case((AccountMembership.role == AccountMembership.ROLE_OWNER, 0), else_=1),
            AccountMembership.id.asc(),
        )
        .first()
    )


def resolve_or_provision_membership(user):
    membership = active_membership_for_user(user)
    if membership or not current_app.config.get("MULTI_TENANT_ENABLED"):
        return membership
    if not current_app.config.get("ACCOUNT_AUTO_PROVISION_LEGACY_USERS"):
        return None

    bootstrap_username = str(current_app.config.get("BOOTSTRAP_ADMIN_USERNAME") or "").strip()
    membership = create_account_for_user(
        user,
        adopt_legacy_data=bool(bootstrap_username and user.username == bootstrap_username),
    )
    db.session.commit()
    return membership


def install_account_session_hooks():
    global _SESSION_HOOKS_INSTALLED
    if _SESSION_HOOKS_INSTALLED:
        return

    @event.listens_for(Session, "before_flush")
    def _assign_account_to_new_rows(session, _flush_context, _instances):
        account_id = current_account_id()
        if not account_id:
            return
        for item in session.new:
            if hasattr(type(item), "account_id") and getattr(item, "account_id", None) is None:
                item.account_id = account_id

    @event.listens_for(Session, "do_orm_execute")
    def _scope_account_queries(execute_state):
        if (
            not execute_state.is_select
            or execute_state.execution_options.get("include_all_accounts")
        ):
            return
        account_id = current_account_id()
        if not account_id:
            return
        statement = execute_state.statement
        for model in ACCOUNT_SCOPED_MODELS:
            statement = statement.options(
                with_loader_criteria(
                    model,
                    lambda cls: cls.account_id == account_id,
                    include_aliases=True,
                    track_closure_variables=True,
                )
            )
        execute_state.statement = statement

    _SESSION_HOOKS_INSTALLED = True
