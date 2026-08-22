#!/usr/bin/env bash
#
# Сторож для scripts/ship.sh.
#
#   bash scripts/test-ship.sh
#
# Зачем. Этим скриптом двигают ветку, которую тянет боевой сервер, и запускают
# его в том числе из облачной сессии — то есть оттуда, где человек в экран не
# смотрит. Значит проверять надо не «работает ли», а **когда он отказывается**:
# на грязном дереве, на незапушенной ветке, на отставшей ветке и на попытке
# перезаписать ветку не-потомком. Каждый из этих отказов — единственное, что
# стоит между опечаткой и живой школой.
#
# gh подменяется заглушкой на PATH: она держит «состояние GitHub» в файлах и
# записывает каждый PATCH. Настоящая сеть тут не нужна и вредна.

set -Eeuo pipefail

SOURCE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)/ship.sh"
[ -f "$SOURCE" ] || { echo "нет $SOURCE"; exit 1; }

PASS=0; FAIL=0
report() {
    if [ "$1" = ok ]; then PASS=$((PASS+1)); printf '  \033[32mok\033[0m   %s\n' "$2"
    else FAIL=$((FAIL+1)); printf '  \033[31mFAIL\033[0m %s\n' "$2"
         [ -n "${3:-}" ] && printf '       %s\n' "$3"; fi
}

make_fixture() {
    local root; root="$(mktemp -d)"
    mkdir -p "$root/origin" "$root/bin"
    git -C "$root/origin" init --quiet --bare
    git -C "$root" clone --quiet "$root/origin" work 2>/dev/null
    local w="$root/work"
    git -C "$w" config user.email t@e.st; git -C "$w" config user.name T

    echo base > "$w/f"; git -C "$w" add -A; git -C "$w" commit --quiet -m base
    git -C "$w" push --quiet origin HEAD:refs/heads/main
    git -C "$w" push --quiet origin HEAD:refs/heads/production
    git -C "$w" checkout --quiet -b feature
    git -C "$w" commit --quiet --allow-empty -m work
    git -C "$w" push --quiet -u origin feature 2>/dev/null

    mkdir -p "$w/scripts"; cp "$SOURCE" "$w/scripts/ship.sh"; chmod +x "$w/scripts/ship.sh"
    # Скрипт обязан лежать внутри дерева (он считает корень от себя), но
    # коммитить его сюда незачем, а грязное дерево — как раз то, на что он
    # отказывается работать. Прячем локально: exclude в индекс не входит.
    echo "/scripts/" >> "$w/.git/info/exclude"

    # состояние «GitHub»: где какая ветка
    git -C "$w" rev-parse origin/main       > "$root/ref-main"
    git -C "$w" rev-parse origin/production > "$root/ref-production"

    cat > "$root/bin/gh" <<'STUB'
#!/usr/bin/env bash
case "$1 $2" in
  "auth status") exit 0 ;;
  "repo view")   echo "test/repo"; exit 0 ;;
esac
path="$2"

# Просьба о пересеве — это созданный коммит и ветка, указанная на него.
# Заглушка выдаёт предсказуемые sha по счётчику и записывает первую строку
# сообщения: именно она и есть смысл просьбы.
case "$path" in
  */git/commits)
      msg="$(printf '%s\n' "$@" | sed -n 's/^message=//p' | head -1)"
      parent="$(printf '%s\n' "$@" | sed -n 's/^parents\[\]=//p' | head -1)"
      n=$(( $(cat "$GH_STATE/counter" 2>/dev/null || echo 0) + 1 ))
      echo "$n" > "$GH_STATE/counter"
      printf 'сообщение=%s родитель=%s\n' "$msg" "${parent:-нет}" >> "$GH_STATE/commits"
      printf 'c%039d\n' "$n"
      exit 0 ;;
  */git/commits/*)
      echo treesha; exit 0 ;;                      # дерево у коммита одно
  */git/refs)
      ref="$(printf '%s\n' "$@" | sed -n 's/^ref=//p')"
      sha="$(printf '%s\n' "$@" | sed -n 's/^sha=//p')"
      echo "${ref##*/} $sha" >> "$GH_STATE/patches"
      echo "$sha" > "$GH_STATE/ref-${ref##*/}"
      echo '{}'; exit 0 ;;
esac

# gh api repos/test/repo/git/refs/heads/<branch> [--jq …] [-X PATCH -f sha=…]
branch="${path##*/}"
file="$GH_STATE/ref-$branch"
if printf '%s\n' "$@" | grep -q PATCH; then
    sha="$(printf '%s\n' "$@" | sed -n 's/^sha=//p')"
    echo "$branch $sha" >> "$GH_STATE/patches"
    echo "$sha" > "$file"
    echo '{}'; exit 0
fi
# Настоящий gh при ошибке печатает **тело ответа** в stdout, минуя --jq.
# Заглушка обязана врать так же: иначе «ветки нет» выглядит здесь пустой
# строкой, а в жизни — стосимвольным json, который уезжает дальше по коду.
if [ ! -f "$file" ]; then
    echo '{"message":"Not Found","status":"404"}'
    exit 1
fi
cat "$file"
STUB
    chmod +x "$root/bin/gh"
    printf '%s\n' "$root"
}

run_in() {
    local root="$1"; shift
    ( export HOME="$root" GH_STATE="$root" PATH="$root/bin:$PATH"
      cd "$root/work" && bash scripts/ship.sh "$@" ) >"$root/out" 2>&1
    echo $?
}
patched() { grep -q "^$2 " "$1/patches" 2>/dev/null; }
said()    { grep -q "$2" "$1/out" 2>/dev/null; }

# --- обычный путь: ветка впереди main ----------------------------------------
t="$(make_fixture)"; code="$(run_in "$t")"
want="$(git -C "$t/work" rev-parse HEAD)"
if [ "$code" = 0 ] && grep -qx "main $want" "$t/patches"; then
    report ok "ветка впереди main — main перематывается на её вершину"
else
    report FAIL "ветка впереди main — main перематывается на её вершину" "код $code; $(cat "$t/patches" 2>/dev/null)"
fi
rm -rf "$t"

# --- прод не двигается без просьбы -------------------------------------------
t="$(make_fixture)"; run_in "$t" >/dev/null
if ! patched "$t" production; then
    report ok "без --prod прод не трогается"
else
    report FAIL "без --prod прод не трогается" "$(cat "$t/patches")"
fi
rm -rf "$t"

# --- --prod-only --yes двигает прод на origin/main ---------------------------
t="$(make_fixture)"
git -C "$t/work" push --quiet origin feature:refs/heads/main
git -C "$t/work" fetch --quiet origin
printf '%s\n' "$(git -C "$t/work" rev-parse origin/main)" > "$t/ref-main"
code="$(run_in "$t" --prod-only --yes)"
want="$(git -C "$t/work" rev-parse origin/main)"
if [ "$code" = 0 ] && grep -qx "production $want" "$t/patches"; then
    report ok "--prod-only двигает прод на origin/main"
else
    report FAIL "--prod-only двигает прод на origin/main" "код $code; $(cat "$t/patches" 2>/dev/null)"
fi
rm -rf "$t"

# --- грязное дерево ----------------------------------------------------------
t="$(make_fixture)"; echo мусор >> "$t/work/f"; code="$(run_in "$t")"
if [ "$code" != 0 ] && ! patched "$t" main && said "$t" "незакоммиченное"; then
    report ok "грязное дерево — отказ"
else report FAIL "грязное дерево — отказ" "код $code"; fi
rm -rf "$t"

# --- ветка не запушена -------------------------------------------------------
t="$(make_fixture)"; git -C "$t/work" commit --quiet --allow-empty -m позже
code="$(run_in "$t")"
if [ "$code" != 0 ] && ! patched "$t" main && said "$t" "не совпадает"; then
    report ok "ветка не запушена — отказ"
else report FAIL "ветка не запушена — отказ" "код $code"; fi
rm -rf "$t"

# --- ветка отстала от main: не перемотка -------------------------------------
t="$(make_fixture)"
git -C "$t/work" checkout --quiet main
git -C "$t/work" commit --quiet --allow-empty -m чужое
git -C "$t/work" push --quiet origin main
git -C "$t/work" checkout --quiet feature
code="$(run_in "$t")"
if [ "$code" != 0 ] && ! patched "$t" main && said "$t" "rebase"; then
    report ok "ветка отстала — отказ и совет перебрать"
else report FAIL "ветка отстала — отказ и совет перебрать" "код $code"; fi
rm -rf "$t"

# --- стоим на main -----------------------------------------------------------
t="$(make_fixture)"; git -C "$t/work" checkout --quiet main; code="$(run_in "$t")"
if [ "$code" != 0 ] && said "$t" "вливать нечего"; then
    report ok "запуск с main — отказ"
else report FAIL "запуск с main — отказ" "код $code"; fi
rm -rf "$t"

# --- ветка на GitHub ушла вперёд: перезаписывать не даём ---------------------
t="$(make_fixture)"
git -C "$t/work" checkout --quiet main
git -C "$t/work" commit --quiet --allow-empty -m "чужое, уже на GitHub"
git -C "$t/work" push --quiet origin main
printf '%s\n' "$(git -C "$t/work" rev-parse main)" > "$t/ref-main"
git -C "$t/work" checkout --quiet feature
git -C "$t/work" rebase --quiet origin/main >/dev/null 2>&1 || true
# теперь main на GitHub не предок ветки? предок — значит подделаем: откатим ref
printf '%s\n' "$(git -C "$t/work" rev-parse main)" > "$t/ref-main"
git -C "$t/work" checkout --quiet -B feature "$(git -C "$t/work" rev-parse main~1)"
git -C "$t/work" commit --quiet --allow-empty -m "своё мимо чужого"
git -C "$t/work" push --quiet --force origin feature 2>/dev/null
code="$(run_in "$t")"
if [ "$code" != 0 ] && ! patched "$t" main; then
    report ok "main ушёл вперёд мимо ветки — отказ, перезаписи нет"
else report FAIL "main ушёл вперёд мимо ветки — отказ, перезаписи нет" "код $code; $(cat "$t/out" | tail -3)"; fi
rm -rf "$t"

# --- --reseed без аргументов: просьба заведена, аргументы оставлены стенду ---
t="$(make_fixture)"
code="$(run_in "$t" --reseed)"
if [ "$code" = 0 ] && patched "$t" staging-seed &&
   grep -q 'сообщение=seed: родитель=нет' "$t/commits" && ! patched "$t" main; then
    report ok "--reseed без аргументов — просьба «seed:», main не трогается"
else
    report FAIL "--reseed без аргументов — просьба «seed:», main не трогается" \
        "код $code; $(cat "$t/commits" 2>/dev/null)"
fi
rm -rf "$t"

# --- --reseed с аргументами: они уезжают в сообщение -------------------------
# Всё после флага уходит в seed_demo целиком, чтобы список его флагов не
# пришлось держать вторым экземпляром здесь.
t="$(make_fixture)"
code="$(run_in "$t" --reseed --flush --rich)"
if [ "$code" = 0 ] && grep -q 'сообщение=seed: --flush --rich' "$t/commits"; then
    report ok "--reseed с аргументами — они в первой строке просьбы"
else
    report FAIL "--reseed с аргументами — они в первой строке просьбы" \
        "код $code; $(cat "$t/commits" 2>/dev/null)"
fi
rm -rf "$t"

# --- вторая просьба встаёт поверх первой -------------------------------------
# Ветка просьб — история пересевов, и родитель делает её читаемой.
t="$(make_fixture)"
run_in "$t" --reseed >/dev/null
code="$(run_in "$t" --reseed --minimal)"
if [ "$code" = 0 ] && [ "$(grep -c . "$t/commits")" = 2 ] &&
   grep -q 'сообщение=seed: --minimal родитель=c0*1$' "$t/commits"; then
    report ok "вторая просьба — потомок первой"
else
    report FAIL "вторая просьба — потомок первой" "код $code; $(cat "$t/commits" 2>/dev/null)"
fi
rm -rf "$t"

# --- пересев не трогает прод -------------------------------------------------
t="$(make_fixture)"
run_in "$t" --reseed --flush >/dev/null
if ! patched "$t" production && ! patched "$t" main; then
    report ok "--reseed не двигает ни main, ни production"
else
    report FAIL "--reseed не двигает ни main, ни production" "$(cat "$t/patches" 2>/dev/null)"
fi
rm -rf "$t"

printf '\n%d прошло, %d упало\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
