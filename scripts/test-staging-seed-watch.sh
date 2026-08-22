#!/usr/bin/env bash
#
# Сторож для scripts/staging-seed-watch.sh.
#
#   bash scripts/test-staging-seed-watch.sh
#
# Зачем он есть. Скрипт сносит базу стенда **без человека перед экраном**, по
# сообщению, приехавшему из другой сессии. Всё, что он умеет неправильно, он
# сделает молча: в crontab нет ни вывода, ни того, кто на него смотрит.
# Поэтому проверяются обе стороны — что он сеет, когда просят, и что он
# отказывается, когда просьба не та; и отдельно самое неприятное свойство:
# **просьба исполняется один раз**. Скрипт, повторяющий упавший посев каждые
# три минуты, сносил бы базу по кругу.
#
# Ничего настоящего не трогает: git-репозиторий поднимается во временном
# каталоге, staging-seed.sh подменяется заглушкой, HOME уводится туда же —
# значит и лог, и замок, и отметка о последней просьбе живут в песочнице.
# Секунда, и без контейнера: scripts/ туда не монтируется.

set -Eeuo pipefail

SOURCE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)/staging-seed-watch.sh"
[ -f "$SOURCE" ] || { echo "нет $SOURCE"; exit 1; }

PASS=0
FAIL=0

report() {
    if [ "$1" = "ok" ]; then
        PASS=$((PASS + 1)); printf '  \033[32mok\033[0m   %s\n' "$2"
    else
        FAIL=$((FAIL + 1)); printf '  \033[31mFAIL\033[0m %s\n' "$2"
        [ -n "${3:-}" ] && printf '       %s\n' "$3"
    fi
}

# Песочница: origin (голый), рабочее дерево, заглушка посева. Путь — в вывод.
make_fixture() {
    local root; root="$(mktemp -d)"

    mkdir -p "$root/origin"
    git -C "$root/origin" init --quiet --bare

    git -C "$root" clone --quiet "$root/origin" work 2>/dev/null
    local w="$root/work"
    git -C "$w" config user.email t@e.st
    git -C "$w" config user.name Test
    echo one > "$w/file"; git -C "$w" add -A
    git -C "$w" commit --quiet -m one
    git -C "$w" push --quiet -u origin HEAD:refs/heads/main

    # По умолчанию машина называет себя стендом
    echo "COMPOSE_PROJECT_NAME=lesson-tracker-staging" > "$w/.env.prod"

    mkdir -p "$w/scripts"
    cp "$SOURCE" "$w/scripts/staging-seed-watch.sh"
    chmod +x "$w/scripts/staging-seed-watch.sh"

    # Посев не сеет, а расписывается в том, с чем его позвали
    cat > "$w/scripts/staging-seed.sh" <<'STUB'
#!/usr/bin/env bash
echo "$*" >> "$HOME/seed-calls"
exit "${FAKE_SEED_CODE:-0}"
STUB
    chmod +x "$w/scripts/staging-seed.sh"

    printf '%s\n' "$root"
}

# Кладёт на ветку staging-seed просьбу с таким сообщением. Коммит делается
# `commit-tree`, чтобы не трогать рабочую ветку песочницы.
request() {
    local w="$1/work" message="$2" sha
    sha="$(git -C "$w" commit-tree 'HEAD^{tree}' -p HEAD -m "$message")"
    git -C "$w" push --quiet -f origin "$sha:refs/heads/staging-seed"
}

run_in() {
    local root="$1"; shift
    ( export HOME="$root"
      cd "$root/work" && "$@" bash scripts/staging-seed-watch.sh ) >/dev/null 2>&1
    echo $?
}

seeded()   { [ -s "$1/seed-calls" ]; }
seed_args() { cat "$1/seed-calls" 2>/dev/null; }
logged()   { grep -q "$2" "$1/.staging-seed.log" 2>/dev/null; }

# --- просьб не было: тишина, а не посев --------------------------------------
# До первой просьбы ветки нет вовсе, и это обычное состояние, а не поломка.
t="$(make_fixture)"
code="$(run_in "$t")"
if [ "$code" = "0" ] && ! seeded "$t"; then
    report ok "ветки просьб нет — посев не зовётся"
else
    report FAIL "ветки просьб нет — посев не зовётся" "код $code, вызовы: $(seed_args "$t")"
fi
rm -rf "$t"

# --- пришла просьба: сеет с её аргументами -----------------------------------
t="$(make_fixture)"
request "$t" "seed: --flush --rich"
code="$(run_in "$t")"
if [ "$code" = "0" ] && [ "$(seed_args "$t")" = "--flush --rich" ]; then
    report ok "просьба с аргументами — сеет ровно ими"
else
    report FAIL "просьба с аргументами — сеет ровно ими" "код $code, вызовы: $(seed_args "$t")"
fi
rm -rf "$t"

# --- та же просьба второй раз: не сеет ---------------------------------------
# Иначе каждые три минуты стенд сносил бы себе базу.
t="$(make_fixture)"
request "$t" "seed: --flush"
run_in "$t" >/dev/null
code="$(run_in "$t")"
if [ "$code" = "0" ] && [ "$(seed_args "$t" | wc -l)" = "1" ]; then
    report ok "та же просьба второй раз — посев не повторяется"
else
    report FAIL "та же просьба второй раз — посев не повторяется" "код $code, вызовы: $(seed_args "$t")"
fi
rm -rf "$t"

# --- новая просьба после исполненной: сеет снова -----------------------------
# Ради этого просьба и сделана коммитом, а не передвинутой веткой: «пересей
# ещё раз» обязано отличаться от «уже сеяли», даже когда main не двигался.
t="$(make_fixture)"
request "$t" "seed: --flush"
run_in "$t" >/dev/null
request "$t" "seed: --minimal"
code="$(run_in "$t")"
if [ "$code" = "0" ] && [ "$(seed_args "$t" | tail -1)" = "--minimal" ]; then
    report ok "новая просьба после исполненной — сеет снова"
else
    report FAIL "новая просьба после исполненной — сеет снова" "код $code, вызовы: $(seed_args "$t")"
fi
rm -rf "$t"

# --- просьба без аргументов: берёт умолчание контура -------------------------
t="$(make_fixture)"
echo "STAGING_SEED_ARGS=--flush --email=кто@где.ru --root" >> "$t/work/.env.prod"
request "$t" "seed:"
code="$(run_in "$t")"
if [ "$code" = "0" ] && [ "$(seed_args "$t")" = "--flush --email=кто@где.ru --root" ]; then
    report ok "просьба без аргументов — берёт их с контура"
else
    report FAIL "просьба без аргументов — берёт их с контура" "код $code, вызовы: $(seed_args "$t")"
fi
rm -rf "$t"

# --- ни в просьбе, ни на контуре: голый --flush ------------------------------
t="$(make_fixture)"
request "$t" "seed:"
code="$(run_in "$t")"
if [ "$code" = "0" ] && [ "$(seed_args "$t")" = "--flush" ]; then
    report ok "аргументов нет нигде — сеет с --flush"
else
    report FAIL "аргументов нет нигде — сеет с --flush" "код $code, вызовы: $(seed_args "$t")"
fi
rm -rf "$t"

# --- сообщение не про посев: отказ, и просьба помечена исполненной -----------
# Помечена — чтобы не жаловаться в лог каждые три минуты до конца времён.
t="$(make_fixture)"
request "$t" "Правлю расписание, не обращайте внимания"
code="$(run_in "$t")"
first_ok=0
[ "$code" != "0" ] && ! seeded "$t" && logged "$t" "не похоже на просьбу" && first_ok=1
lines_before="$(wc -l < "$t/.staging-seed.log")"
run_in "$t" >/dev/null
lines_after="$(wc -l < "$t/.staging-seed.log")"
if [ "$first_ok" = "1" ] && [ "$lines_before" = "$lines_after" ]; then
    report ok "чужое сообщение — отказ один раз, а не каждый тик"
else
    report FAIL "чужое сообщение — отказ один раз, а не каждый тик" \
        "код $code, строк было $lines_before, стало $lines_after"
fi
rm -rf "$t"

# --- аргумент не из списка: отказ, посев не зовётся --------------------------
t="$(make_fixture)"
request "$t" "seed: --flash"
code="$(run_in "$t")"
if [ "$code" != "0" ] && ! seeded "$t" && logged "$t" "не из списка"; then
    report ok "опечатка в аргументе — отказ, а не посев по умолчанию"
else
    report FAIL "опечатка в аргументе — отказ, а не посев по умолчанию" \
        "код $code, вызовы: $(seed_args "$t")"
fi
rm -rf "$t"

# --- контур назвался продом: отказ -------------------------------------------
t="$(make_fixture)"
echo "COMPOSE_PROJECT_NAME=lesson-tracker-prod" > "$t/work/.env.prod"
request "$t" "seed: --flush"
code="$(run_in "$t")"
if [ "$code" != "0" ] && ! seeded "$t" && logged "$t" "не похож на стенд"; then
    report ok "контур назвался продом — отказ"
else
    report FAIL "контур назвался продом — отказ" "код $code, вызовы: $(seed_args "$t")"
fi
rm -rf "$t"

# --- контур не назвался вовсе: тоже отказ ------------------------------------
# Белый список: пустой ответ значит «не знаю, где я», а не «наверное, стенд».
t="$(make_fixture)"
rm -f "$t/work/.env.prod"
request "$t" "seed: --flush"
code="$(run_in "$t")"
if [ "$code" != "0" ] && ! seeded "$t" && logged "$t" "не задан"; then
    report ok "контур не назвался — отказ"
else
    report FAIL "контур не назвался — отказ" "код $code, вызовы: $(seed_args "$t")"
fi
rm -rf "$t"

# --- посев упал: просьба всё равно исполнена ---------------------------------
# Самое неприятное свойство, ради которого сторож и написан: неудача не
# превращается в бесконечный снос базы по кругу.
t="$(make_fixture)"
request "$t" "seed: --flush"
code="$(run_in "$t" env FAKE_SEED_CODE=1)"
before="$(seed_args "$t" | wc -l)"
run_in "$t" >/dev/null
after="$(seed_args "$t" | wc -l)"
if [ "$code" != "0" ] && logged "$t" "ОШИБКА посева" && [ "$before" = "$after" ]; then
    report ok "посев упал — просьба не повторяется сама"
else
    report FAIL "посев упал — просьба не повторяется сама" \
        "код $code, вызовов было $before, стало $after"
fi
rm -rf "$t"

# --- замок занят: пропускаем тик, а не лезем поверх выкатки ------------------
t="$(make_fixture)"
request "$t" "seed: --flush"
( exec 8>"$t/.staging-autodeploy.lock"; flock -n 8
  code="$(run_in "$t")"
  if [ "$code" = "0" ] && ! seeded "$t" && logged "$t" "занят"; then
      report ok "стенд занят выкаткой — тик пропущен"
  else
      report FAIL "стенд занят выкаткой — тик пропущен" "код $code, вызовы: $(seed_args "$t")"
  fi
  printf '%s %s\n' "$PASS" "$FAIL" > "$t/counts" )
read -r PASS FAIL < "$t/counts"
rm -rf "$t"

printf '\n%d прошло, %d упало\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
