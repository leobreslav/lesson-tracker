# Шпаргалка

Короткие команды на каждый день. Подробности — в [DEPLOY.md](DEPLOY.md)
(развёртывание с нуля) и [CLAUDE.md](CLAUDE.md) (устройство проекта).

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

Обе задачи висят в crontab: `03:30` дамп базы, `04:10` копия файлов в
резервный бакет. Лог общий — `~/backups/backup.log`.

```bash
~/lesson-tracker/scripts/backup-db.sh                 # дамп прямо сейчас
~/lesson-tracker/scripts/backup-files.sh --dry-run    # что скопировалось бы
~/lesson-tracker/scripts/backup-files.sh --restore    # вернуть файлы из резерва
tail -50 ~/backups/backup.log
```

Versioning у R2 нет — резерв это второй бакет; подробности и порядок
восстановления в [DEPLOY.md](DEPLOY.md), раздел 10.

## Выкатка

```bash
./push-deploy.sh "что поменялось"   # коммит, пуш и деплой
./push-deploy.sh --deploy-only      # раскатать уже закоммиченное
```

На сервере при старте контейнера сами выполняются `migrate`, `bootstrap` и
`collectstatic`. `bootstrap` идемпотентен: заводит суперпользователя, только
если его нет вообще (адрес и пароль — `BOOTSTRAP_SUPERUSER_*` в `.env.prod`),
и никогда ничего не удаляет.

```bash
ssh leobreslav@194.67.111.40 "cd ~/lesson-tracker && docker compose \
  -f docker-compose.prod.yml -f docker-compose.ssl.yml logs --tail 50 backend"
```
