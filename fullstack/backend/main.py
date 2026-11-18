"""FastAPI application; no simulation executes in an HTTP request."""
import hmac
import logging
import os
import secrets

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .auth import auth_provider, local_session, owner, password_hash
from .jobs import validate
from .store import store

app = FastAPI(title='Systems Lab API', version='1.0.0')
app.add_middleware(CORSMiddleware, allow_origins=os.getenv('ALLOWED_ORIGINS', 'http://localhost:3000,http://127.0.0.1:3000,http://localhost:8080,http://127.0.0.1:8080').split(','), allow_methods=['GET', 'POST'], allow_headers=['Authorization', 'Content-Type'])


@app.middleware('http')
async def bounded_body(request: Request, call_next):
    from starlette.responses import JSONResponse
    if request.method == 'POST':
        body = await request.body()
        limit = 8_000_000 if request.url.path == '/api/import' else 24000
        if len(body) > limit:
            return JSONResponse({'detail': 'Request exceeds 24 KB.'}, status_code=413)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/api/health')
def health():
    return {'status': 'ok', 'storage': 'aws' if os.getenv('STORAGE_MODE') == 'aws' else 'sql'}


@app.get('/api/settings')
def settings():
    from .ai import provider_config
    ai = provider_config()
    provider = auth_provider()
    settings = dict(auth=provider, client_id=os.getenv('COGNITO_CLIENT_ID'), domain=os.getenv('COGNITO_DOMAIN'), issuer=os.getenv('COGNITO_ISSUER'), ai_enabled=ai is not None, ai_provider=ai[0] if ai else None)
    if provider == 'supabase':
        from .supabase_auth import configuration
        settings['supabase_url'], settings['supabase_publishable_key'] = configuration()
    return settings


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)


@app.post('/api/auth/{action}')
def authenticate(action: str, body: Credentials, request: Request):
    if auth_provider() != 'local':
        raise HTTPException(404, 'Use the hosted sign-in page.')
    # Local password authentication is deliberately restricted to local serving.
    if request.client and request.client.host not in ('127.0.0.1', '::1', 'testclient') and os.getenv('ALLOW_LOCAL_AUTH_NETWORK') != 'true':
        raise HTTPException(403, 'Local authentication requires localhost.')
    email = body.email.strip().lower()
    if '@' not in email or action not in ('register', 'login'):
        raise HTTPException(422, 'Enter a valid email and authentication action.')
    db = store()
    if action == 'register':
        salt = secrets.token_hex(16)
        if not db.add_user(email, salt, password_hash(body.password, salt)):
            raise HTTPException(409, 'An account with this email already exists.')
    else:
        user = db.user(email)
        # Hash even unknown users to reduce account enumeration through timing.
        valid = password_hash(body.password, user['salt'] if user else '00' * 16)
        if not user or not hmac.compare_digest(valid, user['password_hash']):
            raise HTTPException(401, 'Email or password is incorrect.')
    return {'access_token': local_session(email), 'email': email}


@app.get('/api/catalog')
def catalog():
    from sim.config import presets
    from sim.challenges import challenges
    return dict(presets=[dict(name=k, story=v.story, try_this=v.try_this, config=v.cfg.to_dict()) for k, v in presets().items()], challenges=[dict(id=c.id, title=c.title, story=c.story, config=c.base.to_dict(), knobs=c.knobs, budget=c.budget, slo=c.slo_text, hints=c.hints) for c in challenges().values()])


class Experiment(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    config: dict
    kind: str = 'simulate'
    challenge: str | None = None


def public(job):
    return {k: v for k, v in job.items() if k not in ('owner', 'result_key')}


@app.post('/api/experiments', status_code=202)
def submit(body: Experiment, user: str = Depends(owner)):
    payload = body.model_dump()
    try:
        validate(payload)
        job = store().create(user, payload)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return public(job)


@app.get('/api/experiments')
def experiments(user: str = Depends(owner)):
    return [public(j) for j in store().list(user)]


@app.get('/api/experiments/{job_id}')
def experiment(job_id: str, user: str = Depends(owner)):
    job = store().get(user, job_id)
    if not job:
        raise HTTPException(404, 'Experiment not found.')
    return public(job)


class Archive(BaseModel):
    version: int
    experiments: list[dict] = Field(max_length=100)


def explanation_source(job_id: str, user: str = Depends(owner)):
    job = store().get(user, job_id)
    if not job:
        raise HTTPException(404, 'Experiment not found.')
    return job, user


@app.post('/api/experiments/{job_id}/explanation')
async def explain_experiment(source=Depends(explanation_source)):
    from .ai import explain
    job, user = source
    return await explain(job, user)


@app.post('/api/import')
def restore(body: Archive, user: str = Depends(owner)):
    if os.getenv('STORAGE_MODE') == 'aws':
        raise HTTPException(403, 'Archive restoration is available in the local application.')
    if body.version != 1:
        raise HTTPException(422, 'Unknown archive version.')
    try:
        for job in body.experiments:
            if job['status'] not in ('completed', 'failed'):
                raise ValueError('Only finished experiments can be restored. Finish active jobs before exporting.')
            Experiment.model_validate(job['payload'])
            int(job['created'])
            if job['status'] == 'completed' and not isinstance(job.get('result'), dict):
                raise ValueError('Completed experiments must contain results.')
        store().restore(user, body.experiments)
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {'imported': len(body.experiments)}


from mangum import Mangum
handler = Mangum(app, lifespan='off')
