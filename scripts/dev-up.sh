#!/usr/bin/env bash
#
# Поднять стек разработки и довести его до рабочего состояния.
#
#   ./scripts/dev-up.sh          # окружение, контейнеры, миграции
#   ./scripts/dev-up.sh --seed   # плюс посев, если база пустая
#
# Быстрый старт был тремя командами, и две из них человек помнил, а третью
# — нет. В облачной сессии их не помнит никто: сессия начинается с чистого
# клона, где нет ни `.env`, ни поднятого демона Docker, ни применённых
# миграций. Отсюда одна дверь на оба случая.
#
# Идемпотентно: поднятый стек не пересоздаётся, а посев в непустую базу не
# идёт вовсе — на своей машине там чужая работа, и молча снести её нельзя.

set -Eeuo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

SEED=0
EMAIL="${SEED_EMAIL:-}"
for arg in "$@"; do
    case "$arg" in
        --seed)   SEED=1 ;;
        --email=*) EMAIL="${arg#--email=}" ;;
        *) printf 'Неизвестный ключ: %s\n' "$arg" >&2; exit 2 ;;
    esac
done

log() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

# Демон Docker. В облачной сессии он установлен, но не запущен — как
# Postgres и Redis там же; на своей машине он обычно уже поднят, и эта
# ветка не выполняется вовсе.
if ! docker info >/dev/null 2>&1; then
    log "Запускаю демон Docker"
    service docker start >/dev/null 2>&1 || dockerd >/tmp/dockerd.log 2>&1 &
    for _ in $(seq 30); do
        docker info >/dev/null 2>&1 && break
        sleep 1
    done
    docker info >/dev/null 2>&1 || {
        printf '\033[31mDocker не поднялся. Лог: /tmp/dockerd.log\033[0m\n' >&2
        exit 1
    }
fi

bash scripts/dev-env.sh

# Стек, и с разбором отказа. Compose про свои беды говорит внятно и сразу
# — «403 Forbidden» от хранилища слоёв Docker Hub, «429 Too Many Requests»
# от реестра, — но не говорит **что с этим делать**, а в облачной сессии
# делать надо не с проектом, а с сетевой политикой окружения. Отсюда эта
# подсказка: без неё сообщение читается как поломка репозитория.
log "Поднимаю стек"
if ! docker compose up -d; then
    cat >&2 <<'HINT'

Стек не поднялся. Если выше отказ сети, а не ошибка сборки — дело не в
репозитории:

  403 Forbidden от production.cloudfront.docker.com
      слои Docker Hub лежат на отдельном хосте, и политика сети окружения
      пускает реестр, но не его. Разрешите этот хост в настройках окружения
      (claude.ai/code -> окружение -> Network access);
  429 Too Many Requests от registry-1.docker.io
      предел анонимных запросов к Docker Hub. Помогает подождать или
      войти -- docker login.

HINT
    exit 1
fi

# Миграции с повтором: контейнер базы объявлен healthcheck'ом, но backend
# стартует вместе с ним, и первая же команда иногда приходит раньше, чем
# Postgres принимает соединения.
log "Применяю миграции"
for attempt in $(seq 10); do
    if docker compose exec -T backend python manage.py migrate --noinput; then
        break
    fi
    [ "$attempt" -eq 10 ] && { printf '\033[31mМиграции не прошли\033[0m\n' >&2; exit 1; }
    sleep 3
done

if [ "$SEED" -eq 1 ]; then
    schools="$(docker compose exec -T backend python -c \
        'import django, os; os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings"); django.setup();
from schools.models import School; print(School.objects.count())' 2>/dev/null | tr -d '\r' | tail -1)"

    if [ "${schools:-0}" != "0" ]; then
        log "Посев пропущен: в базе уже есть школа (${schools})"
        printf 'Пересеять целиком — docker compose exec backend python manage.py seed_demo --flush --email=…\n'
    else
        log "Сею демо-данные"
        if [ -n "$EMAIL" ]; then
            docker compose exec -T backend python manage.py seed_demo --email="$EMAIL"
        else
            # Без адреса набор посеется, но войти в интерфейс будет некем:
            # вход только через Google или дверь «войти как» посеянным.
            docker compose exec -T backend python manage.py seed_demo
            printf '\nСвой аккаунт привязывается ключом --email=вы@example.com\n'
        fi
    fi
fi

log "Готово"
printf 'backend  http://localhost:8000\nfrontend http://localhost:5173\n'
