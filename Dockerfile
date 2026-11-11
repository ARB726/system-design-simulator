FROM python:3.12-slim AS native-build
RUN apt-get update && apt-get install -y --no-install-recommends g++ \
    && rm -rf /var/lib/apt/lists/*
COPY native/mmc.cpp /src/mmc.cpp
RUN g++ -O3 -std=c++17 -Wall -Wextra -Werror /src/mmc.cpp -o /sysdesign-mmc

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    STREAMLIT_SERVER_HEADLESS=true STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    SYSDESIGN_REQUIRE_AUTH=true SYSDESIGN_MAX_ARRIVALS=500000
WORKDIR /app
COPY requirements.txt requirements-production.txt ./
RUN python -m pip install --no-cache-dir -r requirements-production.txt \
    && useradd --create-home --uid 10001 app
COPY --from=native-build /sysdesign-mmc /usr/local/bin/sysdesign-mmc
COPY --chown=app:app . .
USER app
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3).read()"
CMD ["python", "-m", "streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
