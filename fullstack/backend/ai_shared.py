"""Cross-process AI admission and caching in a private PostgreSQL schema."""
import hashlib
import json
import logging
import os
import time
from functools import lru_cache
from typing import NamedTuple
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import BigInteger, Column, Integer, MetaData, String, Table, Text, create_engine, delete, insert, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from .auth import auth_provider


class Lease(NamedTuple):
    owner: str
    token: str
    slot: int


def required():
    return auth_provider() != 'local'


def ready():
    if not required():
        return True
    try:
        return make_url(os.getenv('AI_BUDGET_DATABASE_URL', '')).drivername == 'postgresql+psycopg'
    except (ValueError, SQLAlchemyError):
        return False


@lru_cache(maxsize=2)
def shared_budget(url):
    return SharedBudget(url)


def configured_budget():
    if not ready():
        raise HTTPException(503, 'Shared AI quota storage is not configured for this workspace.')
    return shared_budget(os.environ['AI_BUDGET_DATABASE_URL'])


class SharedBudget:
    def __init__(self, url, clock=None):
        self.clock = clock or time.time
        dialect = make_url(url).get_backend_name()
        self.engine = create_engine(url, pool_size=2, max_overflow=0, pool_timeout=5, pool_pre_ping=True,
                                    connect_args={'sslmode': 'require', 'prepare_threshold': None} if dialect == 'postgresql' else {'timeout': 5, 'check_same_thread': False})
        metadata = MetaData(schema='lab_private' if dialect == 'postgresql' else None)
        self.usage = Table('ai_usage', metadata, Column('window', BigInteger, primary_key=True), Column('subject', String(64), primary_key=True), Column('attempts', Integer, nullable=False))
        self.cache = Table('ai_cache', metadata, Column('key', String(64), primary_key=True), Column('owner', String(254), nullable=False), Column('response', Text), Column('expires', BigInteger, nullable=False), Column('lease_token', String(32)), Column('lease_until', BigInteger, nullable=False))
        self.slots = Table('ai_slots', metadata, Column('id', Integer, primary_key=True), Column('token', String(32), nullable=False), Column('expires', BigInteger, nullable=False))
        # Production tables are created explicitly by the reviewed private-schema migration.
        if dialect == 'sqlite':
            metadata.create_all(self.engine)

    def admit(self, user, key):
        now = int(self.clock())
        window = now // 3600
        subject = hashlib.sha256(user.encode()).hexdigest()
        try:
            with self.engine.begin() as cx:
                if self.engine.dialect.name == 'sqlite':
                    cx.execute(update(self.cache).where(text('1=0')).values(lease_until=0))
                else:
                    cx.execute(text("SELECT pg_advisory_xact_lock(hashtext('systems-lab-ai-admission'))"))
                cx.execute(delete(self.usage).where(self.usage.c.window < window-1))
                cx.execute(delete(self.cache).where(self.cache.c.expires < now-3600, self.cache.c.lease_until < now))
                row = cx.execute(select(self.cache).where(self.cache.c.key == key)).mappings().first()
                if row and row['owner'] != user:
                    raise HTTPException(409, 'The cached explanation belongs to another workspace.')
                if row and row['response'] and row['expires'] > now:
                    return {**json.loads(row['response']), 'cached': True}
                if row and row['lease_until'] > now:
                    raise HTTPException(429, 'An explanation is already running. Try again shortly.', headers={'Retry-After': '15'})
                counts = dict(cx.execute(select(self.usage.c.subject, self.usage.c.attempts).where(self.usage.c.window == window)).all())
                if counts.get(subject, 0) >= 5 or counts.get('global', 0) >= 20:
                    raise HTTPException(429, 'AI request limit reached. Try again in an hour.', headers={'Retry-After': str((window+1)*3600-now)})
                slots = {r['id']: r for r in cx.execute(select(self.slots)).mappings()}
                slot = next((i for i in range(2) if i not in slots or slots[i]['expires'] <= now), None)
                if slot is None:
                    raise HTTPException(429, 'Two explanations are already running. Try again shortly.', headers={'Retry-After': '15'})
                for principal in ('global', subject):
                    if principal in counts:
                        cx.execute(update(self.usage).where(self.usage.c.window == window, self.usage.c.subject == principal).values(attempts=counts[principal]+1))
                    else:
                        cx.execute(insert(self.usage).values(window=window, subject=principal, attempts=1))
                token = uuid4().hex
                lease = dict(lease_token=token, lease_until=now+30)
                if row:
                    cx.execute(update(self.cache).where(self.cache.c.key == key).values(**lease))
                else:
                    cx.execute(insert(self.cache).values(key=key, owner=user, expires=0, **lease))
                if slot in slots:
                    cx.execute(update(self.slots).where(self.slots.c.id == slot).values(token=token, expires=now+30))
                else:
                    cx.execute(insert(self.slots).values(id=slot, token=token, expires=now+30))
            return Lease(user, token, slot)
        except SQLAlchemyError:
            raise HTTPException(503, 'AI quota storage is temporarily unavailable. Please retry.') from None

    def finish(self, key, response=None, lease=None):
        if lease is None:
            return
        user, token, slot = lease
        now = int(self.clock())
        try:
            with self.engine.begin() as cx:
                values = dict(lease_until=0)
                if response is not None:
                    values.update(response=json.dumps(response, allow_nan=False), expires=now+3600)
                cx.execute(update(self.cache).where(self.cache.c.key == key, self.cache.c.owner == user, self.cache.c.lease_token == token).values(**values))
                cx.execute(update(self.slots).where(self.slots.c.id == slot, self.slots.c.token == token).values(expires=0))
        except SQLAlchemyError:
            # A validated answer can still be delivered if cache persistence fails.
            logging.getLogger(__name__).warning('AI cache update unavailable; admission leases will expire.')
