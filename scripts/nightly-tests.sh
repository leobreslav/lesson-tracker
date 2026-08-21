#!/usr/bin/env bash
#
# Ночной прогон: питоновский набор и браузерный, целиком.
#
# Заведён после замера: полный браузерный стоит ~8.5 минут, за сутки работы
# он запускался четырнадцать раз (два часа) и **ни разу** не нашёл того, чего
# не нашли точечные прогоны до него. При этом совсем без него нельзя — он
# единственный, кто ходит по всем экранам разом. Отсюда разделение: днём
# точечный и дымовой, ночью полный.
#
# Ставится в crontab машины разработчика:
#
#     0 3 * * * ~/projects/lesson-tracker/scripts/nightly-tests.sh
#
# Пишет в лог и ничего не чинит: разбирается утром человек.

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${NIGHTLY_LOG:-$HOME/.lesson-tracker-nightly.log}"

cd "$ROOT"

say() { printf '%s  %s\n' "$(date '+%F %T')" "$*" >> "$LOG"; }

# Два прогона разом невозможны: имя compose-проекта у стенда фиксированное, и
# второй запуск пересоздаёт те же контейнеры — то есть сносит стек из-под
# первого. Если человек работает ночью, ночной прогон уступает, а не ломает
# ему набор.
if docker ps --format '{{.Names}}' | grep -q '^lesson-tracker-e2e'; then
    say "пропуск: стенд занят — кто-то гоняет тесты"
    exit 0
fi

commit="$(git rev-parse --short HEAD)"
dirty=""
git diff --quiet || dirty=" (рабочее дерево грязное)"
say "начало, $commit$dirty"

failed=0

if docker compose exec -T backend python manage.py test --noinput > /tmp/nightly-py.log 2>&1; then
    say "питон: $(grep -oE 'Ran [0-9]+ tests[^,]*' /tmp/nightly-py.log | tail -1) — OK"
else
    failed=1
    say "питон: ПАДЕНИЕ"
    grep -E "^(FAIL|ERROR):" /tmp/nightly-py.log | head -20 >> "$LOG" || true
fi

if ./e2e.sh > /tmp/nightly-e2e.log 2>&1; then
    say "браузерный: $(grep -oE '[0-9]+ passed \([^)]*\)' /tmp/nightly-e2e.log | tail -1) — OK"
else
    failed=1
    say "браузерный: ПАДЕНИЕ"
    grep -E "^  +✘" /tmp/nightly-e2e.log | head -20 >> "$LOG" || true
fi

say "конец, итог: $([ $failed -eq 0 ] && echo зелено || echo ЕСТЬ ПАДЕНИЯ)"
exit $failed
