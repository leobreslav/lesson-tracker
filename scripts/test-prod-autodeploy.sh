#!/usr/bin/env bash
#
# Сторож для scripts/prod-autodeploy.sh.
#
#   bash scripts/test-prod-autodeploy.sh
#
# Зачем он есть. Этот скрипт — единственное в проекте, что выкатывает **прод**
# без человека перед экраном. Всё, что он умеет неправильно, он сделает молча:
# в crontab нет ни вывода, ни того, кто на него смотрит. Поэтому проверяются
# обе стороны — и что он выкатывает, когда должен, и что он отказывается,
# когда не должен. Сторож, проверяющий только успех, пропустил бы ровно те
# случаи, ради которых проверки и написаны.
#
# Ничего настоящего не трогает: git-репозиторий поднимается во временном
# каталоге, `docker` и `deploy.sh` подменяются заглушками на PATH, HOME уводится
# туда же — значит и лог, и замок, и метка неудачного fetch'а живут в песочнице.
# Секунда, и без контейнера: scripts/ туда не монтируется.

set -Eeuo pipefail

SOURCE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)/prod-autodeploy.sh"
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

# Собирает песочницу: origin (голый), рабочее дерево, заглушки docker и
# deploy.sh. Возвращает путь через стандартный вывод.
make_fixture() {
    local root; root="$(mktemp -d)"

    mkdir -p "$root/origin" "$root/bin"
    git -C "$root/origin" init --quiet --bare

    git -C "$root" clone --quiet "$root/origin" work 2>/dev/null
    local w="$root/work"
    git -C "$w" config user.email t@e.st
    git -C "$w" config user.name Test
    echo one > "$w/file"; git -C "$w" add -A
    git -C "$w" commit --quiet -m one
    git -C "$w" push --quiet -u origin HEAD:refs/heads/production
    git -C "$w" checkout --quiet -B production
    git -C "$w" branch --quiet --set-upstream-to=origin/production

    mkdir -p "$w/scripts"
    cp "$SOURCE" "$w/scripts/prod-autodeploy.sh"
    chmod +x "$w/scripts/prod-autodeploy.sh"

    # deploy.sh не выкатывает, а расписывается в том, что его позвали
    cat > "$w/deploy.sh" <<'STUB'
#!/usr/bin/env bash
git pull --ff-only --quiet
echo "deploy" >> "$HOME/deploy-calls"
STUB
    chmod +x "$w/deploy.sh"

    # docker ps: по умолчанию машина называет себя продом
    cat > "$root/bin/docker" <<'STUB'
#!/usr/bin/env bash
[ "${1:-}" = "ps" ] || exit 0
printf '%s\n' "${FAKE_PROJECT:-lesson-tracker-prod}-backend-1"
STUB
    chmod +x "$root/bin/docker"

    printf '%s\n' "$root"
}

# Запускает скрипт в песочнице. Печатает код возврата; лог остаётся в $HOME.
run_in() {
    local root="$1"; shift
    ( export HOME="$root" PATH="$root/bin:$PATH"
      cd "$root/work" && "$@" bash scripts/prod-autodeploy.sh ) >/dev/null 2>&1
    echo $?
}

deployed() { [ -s "$1/deploy-calls" ]; }
logged()   { grep -q "$2" "$1/.prod-autodeploy.log" 2>/dev/null; }

# --- ничего не изменилось: тишина, а не выкатка ------------------------------
t="$(make_fixture)"
code="$(run_in "$t")"
if [ "$code" = "0" ] && ! deployed "$t"; then
    report ok "ветка не двигалась — deploy.sh не зовётся"
else
    report FAIL "ветка не двигалась — deploy.sh не зовётся" "код $code, вызовы: $(cat "$t/deploy-calls" 2>/dev/null)"
fi
rm -rf "$t"

# --- ветку передвинули вперёд: выкатывает ------------------------------------
t="$(make_fixture)"
git -C "$t/work" commit --quiet --allow-empty -m two
git -C "$t/work" push --quiet origin HEAD:refs/heads/production
git -C "$t/work" reset --hard --quiet HEAD~1
code="$(run_in "$t")"
if [ "$code" = "0" ] && deployed "$t"; then
    report ok "ветка ушла вперёд — выкатывает"
else
    report FAIL "ветка ушла вперёд — выкатывает" "код $code, лог: $(tail -1 "$t/.prod-autodeploy.log" 2>/dev/null)"
fi
rm -rf "$t"

# --- ветку двинули назад: отказ, прод не трогаем -----------------------------
# git pull --ff-only на откат не согласится, и без этой проверки скрипт упал бы
# внутри deploy.sh невнятной ошибкой git — уже раскатав половину.
t="$(make_fixture)"
git -C "$t/work" commit --quiet --allow-empty -m two
git -C "$t/work" push --quiet origin HEAD:refs/heads/production
git -C "$t/work" fetch --quiet origin
git -C "$t/work" push --quiet --force origin 'HEAD~1:refs/heads/production'
code="$(run_in "$t")"
if [ "$code" != "0" ] && ! deployed "$t" && logged "$t" "ОТКАЗ"; then
    report ok "ветку двинули назад — отказ и прод не тронут"
else
    report FAIL "ветку двинули назад — отказ и прод не тронут" "код $code, вызовы: $(cat "$t/deploy-calls" 2>/dev/null)"
fi
rm -rf "$t"

# --- дерево на чужой ветке: отказ --------------------------------------------
# deploy.sh тянет текущую ветку, а не ту, за которой мы следим: останься сервер
# на main — выкатывалось бы не то, что просили.
t="$(make_fixture)"
git -C "$t/work" checkout --quiet -B main
git -C "$t/work" commit --quiet --allow-empty -m two
git -C "$t/work" push --quiet origin main:refs/heads/production
code="$(run_in "$t")"
if [ "$code" != "0" ] && ! deployed "$t" && logged "$t" "ветке"; then
    report ok "дерево не на production — отказ"
else
    report FAIL "дерево не на production — отказ" "код $code"
fi
rm -rf "$t"

# --- контур назвался стендом: отказ ------------------------------------------
t="$(make_fixture)"
echo "COMPOSE_PROJECT_NAME=lesson-tracker-staging" > "$t/work/.env.prod"
git -C "$t/work" commit --quiet --allow-empty -m two
git -C "$t/work" push --quiet origin HEAD:refs/heads/production
git -C "$t/work" reset --hard --quiet HEAD~1
code="$(run_in "$t")"
if [ "$code" != "0" ] && ! deployed "$t" && logged "$t" "не похож на прод"; then
    report ok "контур назвался стендом — отказ"
else
    report FAIL "контур назвался стендом — отказ" "код $code"
fi
rm -rf "$t"

# --- машина не назвалась вовсе: тоже отказ -----------------------------------
# Белый список: пустой ответ значит «не знаю, где я», а не «наверное, прод».
t="$(make_fixture)"
cat > "$t/bin/docker" <<'STUB'
#!/usr/bin/env bash
exit 0
STUB
chmod +x "$t/bin/docker"
git -C "$t/work" commit --quiet --allow-empty -m two
git -C "$t/work" push --quiet origin HEAD:refs/heads/production
git -C "$t/work" reset --hard --quiet HEAD~1
code="$(run_in "$t")"
if [ "$code" != "0" ] && ! deployed "$t" && logged "$t" "не задан"; then
    report ok "машина не назвалась — отказ"
else
    report FAIL "машина не назвалась — отказ" "код $code"
fi
rm -rf "$t"

# --- упавшая выкатка повторяется, даже когда новых коммитов нет --------------
#
# `deploy.sh` тянет код сам, и падает уже после `git pull`: дерево стоит на
# origin/production, и без отметки следующий тик вышел бы как «нечего
# выкатывать». Причину устранили — а контур молчит до чужого коммита.
t="$(make_fixture)"
cat > "$t/work/deploy.sh" <<'STUB'
#!/usr/bin/env bash
git pull --ff-only --quiet
echo "deploy" >> "$HOME/deploy-calls"
exit 1
STUB
chmod +x "$t/work/deploy.sh"
git -C "$t/work" commit --quiet --allow-empty -m two
git -C "$t/work" push --quiet origin HEAD:refs/heads/production
git -C "$t/work" reset --hard --quiet HEAD~1

first="$(run_in "$t")"
if [ "$first" != "0" ] && [ -f "$t/.prod-autodeploy.failed" ]; then
    report ok "упавшая выкатка оставляет отметку"
else
    report FAIL "упавшая выкатка оставляет отметку" "код $first"
fi

# теперь дерево уже на origin/production — прежний скрипт вышел бы молча
: > "$t/deploy-calls"
cat > "$t/work/deploy.sh" <<'STUB'
#!/usr/bin/env bash
git pull --ff-only --quiet
echo "deploy" >> "$HOME/deploy-calls"
STUB
chmod +x "$t/work/deploy.sh"
second="$(run_in "$t")"
if [ "$second" = "0" ] && deployed "$t" && [ ! -f "$t/.prod-autodeploy.failed" ]; then
    report ok "следующий тик повторяет её и снимает отметку"
else
    report FAIL "следующий тик повторяет её и снимает отметку" \
        "код $second, вызовы: $(cat "$t/deploy-calls" 2>/dev/null)"
fi
rm -rf "$t"

# --- замок занят: пропускаем тик, а не лезем поверх --------------------------
t="$(make_fixture)"
git -C "$t/work" commit --quiet --allow-empty -m two
git -C "$t/work" push --quiet origin HEAD:refs/heads/production
git -C "$t/work" reset --hard --quiet HEAD~1
( exec 8>"$t/.prod-deploy.lock"; flock -n 8
  code="$(run_in "$t")"
  if [ "$code" = "0" ] && ! deployed "$t" && logged "$t" "уже идёт"; then
      report ok "замок занят — тик пропущен"
  else
      report FAIL "замок занят — тик пропущен" "код $code, вызовы: $(cat "$t/deploy-calls" 2>/dev/null)"
  fi
  printf '%s %s\n' "$PASS" "$FAIL" > "$t/counts" )
read -r PASS FAIL < "$t/counts"
rm -rf "$t"

printf '\n%d прошло, %d упало\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
