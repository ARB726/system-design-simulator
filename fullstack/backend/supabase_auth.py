"""Verify Supabase user tokens using public signing keys; no service-role key required."""
import os
from functools import lru_cache
from urllib.parse import urlsplit
from uuid import UUID

import jwt
from fastapi import HTTPException


def configuration():
    url = os.getenv('SUPABASE_URL', '').strip().rstrip('/')
    public_key = os.getenv('SUPABASE_PUBLISHABLE_KEY', '').strip()
    try:
        parsed = urlsplit(url)
    except ValueError:
        raise HTTPException(503, 'Configure a valid HTTPS Supabase project URL.') from None
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise HTTPException(503, 'Configure a valid HTTPS Supabase project URL.')
    # Only deliberately public keys may be returned by /api/settings.
    if not public_key.startswith('sb_publishable_'):
        try:
            public = jwt.decode(public_key, options={'verify_signature': False})
            if public.get('role') != 'anon':
                raise ValueError('Not an anonymous public key')
        except (jwt.PyJWTError, ValueError, AttributeError):
            raise HTTPException(503, 'Configure a Supabase publishable key, never a secret or service-role key.') from None
    return url, public_key


@lru_cache(maxsize=4)
def signing_keys(url):
    return jwt.PyJWKClient(url + '/auth/v1/.well-known/jwks.json', cache_keys=True, lifespan=300, timeout=5)


def verify(token):
    url, _ = configuration()
    try:
        key = signing_keys(url).get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=['ES256', 'RS256'], issuer=url + '/auth/v1', audience='authenticated',
                            options={'require': ['sub', 'exp', 'iat', 'iss', 'aud', 'role']})
        if claims['role'] != 'authenticated' or claims.get('is_anonymous', False):
            raise jwt.InvalidTokenError('A signed-in user is required')
        return 'supabase:' + str(UUID(claims['sub']))
    except jwt.PyJWKClientConnectionError:
        raise HTTPException(503, 'The sign-in service is temporarily unavailable. Please retry.') from None
    except (jwt.PyJWTError, ValueError, TypeError, AttributeError):
        raise HTTPException(401, 'Session expired or invalid. Please sign in again.') from None
