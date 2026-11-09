FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home appuser
COPY app app
COPY frontend frontend
COPY migrations migrations
COPY alembic.ini .
RUN mkdir -p data && chown -R appuser:appuser /srv/app
USER appuser
EXPOSE 8080
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8080 --no-proxy-headers --no-access-log"]
