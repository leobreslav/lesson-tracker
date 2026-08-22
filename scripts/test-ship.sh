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

# --- ВТОРАЯ ДОРОГА: gh не годится --------------------------------------------
#
# Проверок тут столько же, сколько у первой, и это не перестраховка. Дорог две,
# потому что gh есть не везде: в облачной сессии его как раз не оказалось, и
# скрипт умирал первой строкой проверок — то есть был мёртв ровно там, ради
# чего написан. Непроверенная вторая дорога повторила бы это молча.
#
# «Не годится», а не «нет»: заглушка отвечает отказом на `gh auth status`, и
# это ровно то условие, по которому скрипт и ветвится — отсутствие и
# неавторизованность он не различает намеренно, толку от них поровну. Убрать
# gh из PATH по-настоящему нельзя: вместе с ним ушли бы git и всё остальное.
# Поэтому каждая проверка заодно смотрит, что скрипт **сказал**, какой дорогой
# идёт: без этого «прошло» значило бы только «ветка встала куда надо», а какой
# из двух дорог — неизвестно.
#
# Смотрим на настоящий bare-репозиторий, а не на журнал заглушки: раз пуш идёт
# git'ом, единственная правда о том, куда встала ветка, лежит в самом origin.

run_bare() {
    local root="$1"; shift
    ( export HOME="$root" PATH="$root/nogh:$PATH"
      cd "$root/work" && bash scripts/ship.sh "$@" ) >"$root/out" 2>&1
    echo $?
}
# Каталог с отказывающей заглушкой встаёт первым в PATH и перекрывает
# настоящий gh, если он на машине есть.
hide_gh() { mkdir -p "$1/nogh"; printf '#!/bin/sh\nexit 127\n' > "$1/nogh/gh"; chmod +x "$1/nogh/gh"; }
# Пошёл ли скрипт второй дорогой — по его собственным словам.
by_git() { grep -q "обычным пушем" "$1/out" 2>/dev/null; }
at() { git -C "$1/origin" rev-parse "$2" 2>/dev/null; }

# --- перемотка main без gh ---------------------------------------------------
t="$(make_fixture)"; hide_gh "$t"
want="$(git -C "$t/work" rev-parse HEAD)"
code="$(run_bare "$t")"
if [ "$code" = 0 ] && by_git "$t" && [ "$(at "$t" main)" = "$want" ]; then
    report ok "без gh: main перематывается обычным пушем"
else
    report FAIL "без gh: main перематывается обычным пушем" "код $code; $(tail -3 "$t/out")"
fi
rm -rf "$t"

# --- без gh прод по-прежнему не двигается без просьбы ------------------------
t="$(make_fixture)"; hide_gh "$t"
was="$(at "$t" production)"
run_bare "$t" >/dev/null
if by_git "$t" && [ "$(at "$t" production)" = "$was" ]; then
    report ok "без gh: без --prod прод не трогается"
else
    report FAIL "без gh: без --prod прод не трогается" "$(at "$t" production)"
fi
rm -rf "$t"

# --- без gh --prod-only двигает прод на origin/main --------------------------
t="$(make_fixture)"; hide_gh "$t"
git -C "$t/work" push --quiet origin feature:refs/heads/main
git -C "$t/work" fetch --quiet origin
want="$(git -C "$t/work" rev-parse origin/main)"
code="$(run_bare "$t" --prod-only --yes)"
if [ "$code" = 0 ] && by_git "$t" && [ "$(at "$t" production)" = "$want" ]; then
    report ok "без gh: --prod-only двигает прод на origin/main"
else
    report FAIL "без gh: --prod-only двигает прод на origin/main" "код $code; $(tail -3 "$t/out")"
fi
rm -rf "$t"

# --- без gh перезаписи не-потомком тоже нет ----------------------------------
# Самый важный из отказов: на том конце боевой сервер. Здесь он должен
# случиться **до** пуша, а не разбиться о сервер, — иначе на настоящем GitHub
# отказ выглядел бы чужой ошибкой посреди чужого вывода.
t="$(make_fixture)"; hide_gh "$t"
git -C "$t/work" checkout --quiet main
git -C "$t/work" commit --quiet --allow-empty -m "чужое, уже на GitHub"
git -C "$t/work" push --quiet origin main
git -C "$t/work" checkout --quiet -B feature "$(git -C "$t/work" rev-parse main~1)"
git -C "$t/work" commit --quiet --allow-empty -m "своё мимо чужого"
git -C "$t/work" push --quiet --force origin feature 2>/dev/null
was="$(at "$t" main)"
code="$(run_bare "$t")"
if [ "$code" != 0 ] && by_git "$t" && [ "$(at "$t" main)" = "$was" ]; then
    report ok "без gh: main ушёл вперёд мимо ветки — отказ, перезаписи нет"
else
    report FAIL "без gh: main ушёл вперёд мимо ветки — отказ, перезаписи нет" \
        "код $code; $(tail -3 "$t/out")"
fi
rm -rf "$t"

# --- без gh просьба о пересеве — настоящий коммит ----------------------------
t="$(make_fixture)"; hide_gh "$t"
code="$(run_bare "$t" --reseed --flush --rich)"
first="$(git -C "$t/origin" log -1 --format=%s staging-seed 2>/dev/null || true)"
tree_ok=0
[ "$(git -C "$t/origin" rev-parse 'staging-seed^{tree}' 2>/dev/null)" = \
  "$(git -C "$t/origin" rev-parse 'main^{tree}' 2>/dev/null)" ] && tree_ok=1
if [ "$code" = 0 ] && by_git "$t" && [ "$first" = "seed: --flush --rich" ] && [ "$tree_ok" = 1 ]; then
    report ok "без gh: просьба о пересеве — коммит с деревом main и аргументами в шапке"
else
    report FAIL "без gh: просьба о пересеве — коммит с деревом main и аргументами в шапке" \
        "код $code; «$first»; дерево совпало: $tree_ok; $(tail -3 "$t/out")"
fi
rm -rf "$t"

# --- без gh вторая просьба встаёт поверх первой ------------------------------
t="$(make_fixture)"; hide_gh "$t"
run_bare "$t" --reseed >/dev/null
first="$(at "$t" staging-seed)"
code="$(run_bare "$t" --reseed --minimal)"
second="$(at "$t" staging-seed)"
if [ "$code" = 0 ] && by_git "$t" && [ "$second" != "$first" ] &&
   [ "$(git -C "$t/origin" rev-parse 'staging-seed^' 2>/dev/null)" = "$first" ]; then
    report ok "без gh: вторая просьба — потомок первой"
else
    report FAIL "без gh: вторая просьба — потомок первой" "код $code; $(tail -3 "$t/out")"
fi
rm -rf "$t"

printf '\n%d прошло, %d упало\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
