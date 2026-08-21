FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Слоя с apt тут нет намеренно. Стояли build-essential и libpq-dev — под
# сборку psycopg из исходников, — но в requirements значится
# `psycopg[binary]`, а он приезжает готовым колесом со своей libpq внутри.
# Компилировать нечего, и остального в проекте нет: openpyxl, pypdf, boto3
# и anthropic — чистый Python либо колёса.
#
# Убрано не ради красоты: образ 863 МБ против 409, сборка быстрее, и —
# главное — из проекта исчезает единственная зависимость от deb.debian.org.
# В облачной сессии сборка на нём и спотыкалась: сеть там по списку, apt
# ходит plain HTTP, и разрешать ему домен пришлось бы отдельно. Фронт этой
# беды не знал никогда — он на alpine, где apt нет вовсе.
#
# Понадобится пакет из системы — возвращайте слой, но проверьте сперва, не
# ставится ли зависимость колесом: за десять лет это стало правилом, а не
# исключением.
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
