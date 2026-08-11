FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000


# Разработка: код приезжает bind-mount'ом, runserver сам перезагружается
FROM base AS dev

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]


# Прод: код зашит в образ, отдаёт gunicorn
FROM base AS prod

CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--access-logfile", "-"]
