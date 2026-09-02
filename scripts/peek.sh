#!/usr/bin/env bash
#
# Взглянуть на экран разработки — секундами, а не подъёмом стенда.
#
#   ./scripts/peek.sh /plan --shot вид.png
#   ./scripts/peek.sh /plan 'document.querySelectorAll(".showcase-line").length'
#   ./scripts/peek.sh /library/3 --as petrov@example.com --shot .
#
# ЗАЧЕМ. Половина браузерных запусков в этом проекте — не «проверить, что не
# сломалось», а «сколько пикселей»: высота карточки, куда встала плашка, не
# уехала ли кнопка. Стоил такой взгляд полутора минут — `e2e.sh` гасит стек
# разработки, собирает прод-подобный стенд и поднимает его, — и именно эта
# цена превращала один вопрос в семь подъёмов за сессию.
#
# Здесь ничего не собирается и не гасится: dev-сервер уже работает на 5173,
# браузер лежит в образе playwright, и весь взгляд занимает секунды.
#
# ЧЕМ ЭТО НЕ ЯВЛЯЕТСЯ. Заменой браузерным тестам — ни в коем случае. Те гоняют
# **собранный бандл** за nginx, и ловят они ровно то, чего dev-сервер не
# показывает: ошибку, которая вылезает только в сборке. Здесь всё наоборот —
# незасчитанный взгляд на живой экран. Прогон остаётся прогоном, и правило про
# него не меняется: он идёт на шаг работы и по просьбе человека.
#
# Вход через ту же дверь, что у тестов (`POST /api/test/login/`), поэтому
# нужен `E2E_TEST_LOGIN=true` в `.env` — в разработке он и так стоит.

set -Eeuo pipefail

REPO_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$REPO_DIR"

WHO="ivanova@example.com"
FRONT="http://localhost:5173"
SHOT=""
EVAL=""
PATH_TO_OPEN="/"
WIDTH=1280
HEIGHT=900

fail() { printf '\033[31mОшибка: %s\033[0m\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --as)     WHO="$2"; shift 2 ;;
        --shot)   SHOT="$2"; shift 2 ;;
        --size)   WIDTH="${2%%x*}"; HEIGHT="${2##*x}"; shift 2 ;;
        -h|--help) sed -n '3,/^$/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        /*)       PATH_TO_OPEN="$1"; shift ;;
        *)        EVAL="$1"; shift ;;
    esac
done

[ -n "$SHOT" ] || [ -n "$EVAL" ] || fail "нечего делать: нужен --shot или выражение"

# Снимки складываем в один каталог: он в .gitignore, и разбросанные по корню
# png — это мусор, который потом коммитят по недосмотру.
if [ -n "$SHOT" ]; then
    mkdir -p .peek
    case "$SHOT" in
        .) SHOT="$(date +%H%M%S).png" ;;
    esac
    SHOT="${SHOT##*/}"
fi

curl -sf -o /dev/null "$FRONT" \
    || fail "dev-сервер не отвечает на $FRONT — поднимите стек: ./scripts/dev-up.sh"

[ -d e2e/node_modules/playwright-core ] || [ -d e2e/node_modules/@playwright ] \
    || fail "нет e2e/node_modules — прогоните один раз ./e2e.sh, он их поставит"

# `--network host`: страница живёт на хосте, а не в compose-сети. Иначе
# пришлось бы гадать про host.docker.internal, которого в Linux нет.
#
# `--user`: снимок обязан принадлежать человеку, а не root. Иначе взгляд на
# экран оставляет за собой файл, который сам же смотрящий не может удалить, —
# та самая беда из «Особенностей окружения», только заведённая заново.
# `HOME=/tmp` — playwright пишет в домашний каталог, а у чужого uid его нет.
docker run --rm --network host \
    --user "$(id -u):$(id -g)" \
    -e HOME=/tmp \
    -v "$REPO_DIR/e2e:/e2e" \
    -v "$REPO_DIR/.peek:/peek" \
    -e NODE_PATH=/e2e/node_modules \
    -e PEEK_PATH="$PATH_TO_OPEN" \
    -e PEEK_WHO="$WHO" \
    -e PEEK_EVAL="$EVAL" \
    -e PEEK_SHOT="$SHOT" \
    -e PEEK_WIDTH="$WIDTH" \
    -e PEEK_HEIGHT="$HEIGHT" \
    -w /e2e \
    mcr.microsoft.com/playwright:v1.56.0-noble \
    node -e '
const { chromium } = require("playwright-core")

;(async () => {
  const front = "http://localhost:5173"
  const answer = await fetch("http://localhost:8000/api/test/login/", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email: process.env.PEEK_WHO }),
  })
  if (!answer.ok) {
    console.error(`дверь входа ответила ${answer.status}: E2E_TEST_LOGIN включён?`)
    process.exit(1)
  }
  const { key } = await answer.json()

  const browser = await chromium.launch()
  const page = await browser.newPage({
    viewport: {
      width: Number(process.env.PEEK_WIDTH),
      height: Number(process.env.PEEK_HEIGHT),
    },
  })
  // токен кладётся до первой загрузки: приложение читает его при старте
  await page.addInitScript(
    ([token]) => window.localStorage.setItem("authToken", token),
    [key],
  )

  const problems = []
  page.on("console", (m) => m.type() === "error" && problems.push(m.text()))
  page.on("pageerror", (e) => problems.push(String(e)))

  await page.goto(front + process.env.PEEK_PATH, { waitUntil: "networkidle" })

  if (process.env.PEEK_EVAL) {
    const value = await page.evaluate(`(() => (${process.env.PEEK_EVAL}))()`)
    console.log(JSON.stringify(value, null, 1))
  }
  if (process.env.PEEK_SHOT) {
    await page.screenshot({ path: "/peek/" + process.env.PEEK_SHOT, fullPage: true })
    console.log("снимок: .peek/" + process.env.PEEK_SHOT)
  }

  // Ошибки консоли печатаем всегда: ради них браузерные тесты и заведены,
  // и молчать о них здесь значило бы показать красивую картинку сломанного
  // экрана.
  if (problems.length) console.error("в консоли:", ...problems)

  await browser.close()
})().catch((error) => {
  console.error(String(error))
  process.exit(1)
})
'
