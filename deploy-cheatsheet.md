# Шпаргалка

Короткие команды на каждый день. Подробности — в [DEPLOY.md](DEPLOY.md)
(развёртывание с нуля) и [CLAUDE.md](CLAUDE.md) (устройство проекта).

## Три env-файла

| файл | для чего | `DEBUG` | база | бакет R2 |
|---|---|---|---|---|
| `~/projects/lesson-tracker/.env` | обычная разработка: runserver, Vite, `seed_demo` | `True` | dev-том | dev |
| `~/secrets/lesson-tracker.env.local-prod` | локальная проверка **прод-сборки** на `http://localhost` | `False` | том prod-стека | dev |
| `~/secrets/lesson-tracker.env.prod` | боевой; копия того, что лежит на сервере | `False` | боевая | **прод** |

Оба файла из `~/secrets/` лежат **вне репозитория** намеренно: `git add -A`
в `push-deploy.sh` берёт всё подряд.

**Секреты у всех трёх разные, и это не формальность.** Единственное, что
общее, — ключи Google (клиент один, `http://localhost` в разрешённых
origins). Боевой бакет R2 не подключается ни к чему, кроме сервера:
`seed_demo --flush` чистит бакет целиком, и один запуск не с тем файлом
унёс бы все вложения школы. По той же причине у прод-стека на ноутбуке
dev-бакет, а не боевой.

Наверх, в `.env.prod` рядом с проектом, файл попадает только на время
проверки — `docker-compose.prod.yml` читает `env_file: .env.prod` и другого
имени не знает:

```bash
cp ~/secrets/lesson-tracker.env.local-prod .env.prod
docker compose -f docker-compose.prod.yml up -d --build   # http://localhost
docker compose -f docker-compose.prod.yml down            # том с базой остаётся
rm .env.prod                                              # чтобы не путался
```

Стек поднимается рядом с dev: у него своё имя проекта
(`lesson-tracker-prod`) и свои порты — 80 и 443 против 5173 и 8000. Логин
через Google работает, но школы в пустой базе нет; чтобы попасть хотя бы в
`/admin/`, в файле есть закомментированная пара `BOOTSTRAP_SUPERUSER_*`.

Боевой файл на ноутбуке нужен не для запуска, а для выкатки: его везёт
`push-deploy.sh`. Запускать с ним что-либо локально не надо.

## Быстрый старт разработки

База с нуля и правдоподобные данные, чтобы было на что смотреть:

```bash
docker compose down -v && docker compose up -d
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py seed_demo --email=leobreslav@gmail.com
```

`--email` привязывает ваш аккаунт к созданной школе администратором: без
этого войти в интерфейс нельзя, вход только через Google, а выдуманные
учётки в Google не существуют. Если вы ещё ни разу не входили, команда
оставит приглашение — первый вход через Google подхватит его.

Флаги `seed_demo`:

| | |
|---|---|
| `--flush` | снести всё (кроме суперпользователей) и создать заново |
| `--minimal` | только школа, год и курсы — без расписания и планов |
| `--email=...` | привязать существующий аккаунт администратором школы |

Команда **не работает при `DEBUG=False`** — это выдуманные данные, на боевой
базе им не место. Повторный запуск без `--flush` ничего не дублирует.

## Браузерные тесты

```bash
./e2e.sh                      # весь набор
./e2e.sh plan                 # только файлы с «plan» в имени
./e2e.sh -g "перетаскивание"  # по названию теста
./e2e.sh --keep               # оставить стек на http://localhost:8080
```

Поднимается отдельный стек (`docker-compose.e2e.yml`): nginx с **собранным**
бандлом, gunicorn, база в памяти. Dev-сервер тут не годится — половина того,
что ломается, ломается только в сборке.

Каждый тест начинается со сброса базы через `seed_demo --flush`, поэтому
порядок и остатки от соседей ни на что не влияют.

**Любая ошибка в консоли браузера роняет тест** — ради этого всё и затевалось.
Скриншот и трасса падения остаются в `e2e/test-results/`; трассу смотреть так:

```bash
docker compose -f docker-compose.e2e.yml run --rm e2e \
  npx playwright show-trace test-results/<папка>/trace.zip
```

Прогонять после любой правки фронтенда — питоновские тесты этот класс ошибок
не видят.

## Каждый день

```bash
docker compose up -d                                   # поднять
docker compose logs -f backend                         # логи
docker compose exec backend python manage.py test      # тесты бэкенда
docker compose exec frontend npm test                  # тесты фронтенда
docker compose exec backend python manage.py migrate   # применить миграции
```

После `makemigrations` и `startapp` файлы принадлежат root:

```bash
sudo chown -R $USER:$USER backend
```

Либо сразу от своего имени, и тогда `chown` не нужен:

```bash
docker compose exec --user "$(id -u):$(id -g)" backend \
  python manage.py makemigrations
```

Файлы уроков лежат в R2, а не на диске. Что там осталось лишнего:

```bash
docker compose exec backend python manage.py cleanup_orphaned_files
docker compose exec backend python manage.py cleanup_orphaned_files --delete
```

Штатно она не находит ничего. `seed_demo --flush` чистит dev-бакет сам, а
тесты в R2 не ходят вовсе — хранилище им подменяет `config/testing.py`.

## Бэкапы (на сервере)

Обе задачи висят в crontab: `03:30` дамп базы, `04:00` копия файлов в
резервный бакет `lesson-tracker-backup`. Логи разные — `~/backups/backup.log`
и `~/backups/files.log`.

```bash
~/lesson-tracker/scripts/backup-db.sh                 # дамп прямо сейчас
~/lesson-tracker/scripts/backup-files.sh --dry-run    # что скопировалось бы
~/lesson-tracker/scripts/backup-files.sh --restore    # вернуть файлы из резерва
tail -50 ~/backups/backup.log ~/backups/files.log
```

Versioning у R2 нет — резерв это второй бакет; подробности и порядок
восстановления в [DEPLOY.md](DEPLOY.md), раздел 10.

## Выкатка

```bash
./push-deploy.sh "что поменялось"   # коммит, пуш и деплой
./push-deploy.sh --deploy-only      # раскатать уже закоммиченное
./push-deploy.sh --skip-env "…"     # не трогать .env.prod на сервере
```

По дороге скрипт везёт на сервер `.env.prod` из
`~/secrets/lesson-tracker.env.prod` (путь — `DEPLOY_ENV_FILE`). Главная копия
файла живёт на ноутбуке; **на сервере его руками не правят**. Если всё-таки
поправили — сначала заберите оттуда, потом меняйте локально:

```bash
scp leobreslav@194.67.111.40:~/lesson-tracker/.env.prod \
    ~/secrets/lesson-tracker.env.prod
```

На сервере при старте контейнера сами выполняются `migrate`, `bootstrap` и
`collectstatic`. `bootstrap` идемпотентен: заводит суперпользователя, только
если его нет вообще (адрес и пароль — `BOOTSTRAP_SUPERUSER_*` в `.env.prod`),
и никогда ничего не удаляет.

```bash
ssh leobreslav@194.67.111.40 "cd ~/lesson-tracker && docker compose \
  -f docker-compose.prod.yml -f docker-compose.ssl.yml logs --tail 50 backend"
```
