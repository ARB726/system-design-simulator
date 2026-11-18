"""Run the complete application locally without an AWS account or Docker."""
import argparse
import functools
import http.server
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--api-port', type=int, default=8000)
    args = parser.parse_args()
    os.chdir(ROOT)
    public = ROOT / 'fullstack/frontend/out'
    if not (public / 'index.html').exists():
        parser.error('Build the frontend first: cd fullstack/frontend && npm ci && npm run build')
    import json
    (public / 'runtime-config.json').write_text(json.dumps({'apiUrl': f'http://127.0.0.1:{args.api_port}'}))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', args.port), functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(public)))
    environment = dict(os.environ)
    environment.setdefault('ALLOWED_ORIGINS', f'http://127.0.0.1:{args.port},http://localhost:{args.port}')
    worker_environment = {k: v for k, v in environment.items() if k not in ('OPENAI_API_KEY', 'GEMINI_API_KEY')}
    children = [subprocess.Popen([sys.executable, '-m', 'uvicorn', 'fullstack.backend.main:app', '--host', '127.0.0.1', '--port', str(args.api_port), '--no-proxy-headers'], env=environment), subprocess.Popen([sys.executable, '-m', 'fullstack.backend.worker'], env=worker_environment)]
    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    print(f'Open http://127.0.0.1:{args.port} — local data persists in data/fullstack.db', flush=True)
    try:
        server.serve_forever(poll_interval=.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        for child in children:
            child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()


if __name__ == '__main__':
    main()
