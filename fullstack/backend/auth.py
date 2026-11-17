"""Local password sessions and verified Cognito access tokens."""
import hashlib
import hmac
import os
import secrets
import time
from functools import lru_cache
from pathlib import Path

import jwt
from fastapi import Header, HTTPException


@lru_cache
def secret():
    if os.getenv('LOCAL_SESSION_SECRET'):
        return os.environ['LOCAL_SESSION_SECRET']
    path = Path('data/fullstack-session.key')
    path.parent.mkdir(exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, 'w') as f:
            f.write(secrets.token_hex(32))
    return path.read_text()


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()


def local_session(email):
    return jwt.encode({'sub': email, 'iss': 'systems-lab-local', 'aud': 'systems-lab', 'iat': int(time.time()), 'exp': int(time.time()) + 28800}, secret(), algorithm='HS256')


@lru_cache
def jwks():
    return jwt.PyJWKClient(os.environ['COGNITO_ISSUER'] + '/.well-known/jwks.json', cache_keys=True, timeout=5)


def owner(authorization: str = Header(default='')):
    if not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Please sign in.')
    token = authorization[7:]
    try:
        if os.getenv('STORAGE_MODE') == 'aws':
            key = jwks().get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=['RS256'], issuer=os.environ['COGNITO_ISSUER'], options={'verify_aud': False, 'require': ['sub', 'exp', 'iss', 'token_use', 'client_id']})
            if claims['token_use'] != 'access' or not hmac.compare_digest(claims['client_id'], os.environ['COGNITO_CLIENT_ID']):
                raise jwt.InvalidTokenError('Wrong token type or client')
        else:
            claims = jwt.decode(token, secret(), algorithms=['HS256'], issuer='systems-lab-local', audience='systems-lab', options={'require': ['sub', 'exp']})
        return claims['sub']
    except jwt.PyJWTError as exc:
        raise HTTPException(401, 'Session expired or invalid. Please sign in again.') from exc
