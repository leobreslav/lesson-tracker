#!/usr/bin/env bash
#
# Прогрев облачного окружения — это текст для поля «Setup script» в
# настройках окружения на claude.ai/code.
#
# Копия лежит в репозитории по двум причинам: её правят как код (в диалоге
# она набирается один раз и потом никем не читается), и по ней видно, чем
# облачное окружение отличается от машины разработчика.
#
# Площадка ставит три условия, и все три тут учтены:
#
#   выйти нулём      ненулевой код не даёт сессии стартовать вовсе, поэтому
#                    каждая команда прикрыта `|| true`;
#   уложиться в пять минут  иначе не построится снимок файловой системы,
#                    ради которого всё это и делается;
#   сеть по списку   образы тянутся с Docker Hub и mcr.microsoft.com — оба
#                    в списке уровня Trusted, ключей и токенов тут не нужно.
#
# Что даёт снимок: образы остаются на диске, и следующая сессия начинает с
# готовыми. Запущенные процессы снимок не хранит — стек в каждой сессии
# поднимает `./scripts/dev-up.sh`.

set -u

# Каталог репозитория. Рабочий каталог скрипта площадкой не обещан, поэтому
# ищем корень по двум приметам сразу: одного `docker-compose.yml` мало.
root="$(pwd)"
if [ ! -f "$root/docker-compose.yml" ] || [ ! -f "$root/CLAUDE.md" ]; then
    root="$(find /root /home /workspace -maxdepth 4 -name CLAUDE.md 2>/dev/null \
        | while read -r f; do [ -f "$(dirname "$f")/docker-compose.yml" ] && dirname "$f" && break; done)"
fi
[ -n "${root:-}" ] && cd "$root" || exit 0

# Демон Docker: установлен, но не запущен — как Postgres и Redis там же.
docker info >/dev/null 2>&1 || service docker start >/dev/null 2>&1 || true
for _ in $(seq 20); do docker info >/dev/null 2>&1 && break; sleep 1; done

# `.env` до всякого compose: без него `env_file: .env` роняет даже сборку.
bash scripts/dev-env.sh || true

# Базовые образы — параллельно: они мелкие, и на них стоят обе сборки.
docker pull postgres:16-alpine >/dev/null 2>&1 &
docker pull python:3.12-slim   >/dev/null 2>&1 &
docker pull node:22-alpine     >/dev/null 2>&1 &
docker pull nginx:1.27-alpine  >/dev/null 2>&1 &

# Образ Playwright — два гигабайта, и тянуть его в первой же сессии ради
# `./e2e.sh --smoke` значит ждать его молча. Уходит в фон и догоняет.
docker pull mcr.microsoft.com/playwright:v1.56.0-noble >/dev/null 2>&1 &

wait

# Сборка своих образов кладёт в снимок и колёса pip, и node_modules —
# самую долгую часть первого запуска.
docker compose build >/dev/null 2>&1 || true
docker compose -f docker-compose.e2e.yml build >/dev/null 2>&1 || true

exit 0
