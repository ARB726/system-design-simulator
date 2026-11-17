FROM python:3.12-slim
WORKDIR /app
COPY fullstack/backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home lab
COPY sim /app/sim
COPY data/optima.json /app/data/optima.json
COPY fullstack/backend /app/fullstack/backend
RUN mkdir -p /app/data && chown -R lab:lab /app
USER lab
EXPOSE 8000
CMD ["uvicorn", "fullstack.backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
