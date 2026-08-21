# Деплой на сервер

Сервер: `194.67.111.40`, Ubuntu 24.04, пользователь `leobreslav`, вход по
SSH-ключу. Домен `lbreslav.com` резолвится на этот IP. Docker установлен,
в ufw открыты 22/80/443.

Дальше предполагается, что репозиторий лежит в `/home/leobreslav/lesson-tracker`.
Если выберете другой путь — поправьте его в `scripts/reload-nginx.sh`
(переменная `REPO_DIR`) и в строке cron.

Шаги идут строго по порядку: HTTPS настраивается только после того, как
приложение заработало по HTTP, иначе certbot не сможет подтвердить домен.

---

## 1. Клонирование репозитория

```bash
ssh leobreslav@194.67.111.40

# ключ для доступа к приватному репозиторию, если он ещё не заведён
ssh-keygen -t ed25519 -C "lesson-tracker-server"
cat ~/.ssh/id_ed25519.pub
# добавьте вывод в GitHub -> Settings -> SSH and GPG keys (или Deploy keys)

git clone git@github.com:leobreslav/lesson-tracker.git ~/lesson-tracker
cd ~/lesson-tracker
```

Проверьте, что вы в группе `docker` (иначе `deploy.sh` откажется работать):

```bash
groups | grep -q docker && echo "ок" || sudo usermod -aG docker "$USER"
# если группу добавляли — перелогиньтесь: exit, затем ssh заново
```

---

## 2. Файл `.env.prod`

**Главная копия файла — на ноутбуке, а не на сервере.** Она лежит вне
репозитория, по умолчанию в `~/secrets/lesson-tracker.env.prod`, и оттуда её
везёт `push-deploy.sh` перед каждым деплоем. На сервере файл **руками не
редактируют**: правка там живёт до первой выкатки, а потом молча заменяется
копией с ноутбука.

Почему так. В git файл попасть не может (он в `.gitignore`, а `push-deploy.sh`
отдельно проверяет, что секретов нет ни в индексе, ни в рабочем дереве),
значит, единственный способ довезти его до сервера — копирование. А если
копирование одностороннее, то у файла должен быть один хозяин, иначе
однажды выкатка затрёт правку, о которой никто не помнил. Хозяин — ноутбук.

Первый раз файл заводится на ноутбуке:

```bash
mkdir -p ~/secrets && chmod 700 ~/secrets
cp .env.prod.example ~/secrets/lesson-tracker.env.prod
chmod 600 ~/secrets/lesson-tracker.env.prod
```

Рядом, в том же `~/secrets/`, живёт `lesson-tracker.env.local-prod` — им
проверяют прод-сборку на `http://localhost`. Он **не боевой**: свой
`SECRET_KEY`, свой пароль базы и dev-бакет R2. Что из них когда берут —
в [deploy-cheatsheet.md](deploy-cheatsheet.md).

Путь можно поменять переменной `DEPLOY_ENV_FILE`. Важно только, чтобы он был
**вне папки проекта**: `git add -A` в `push-deploy.sh` берёт всё подряд, и
файл внутри репозитория рано или поздно уехал бы в историю. Скрипт это
проверяет и отказывается работать.

Сгенерируйте два секрета — **не переиспользуйте dev-значения**:

```bash
# SECRET_KEY
docker run --rm python:3.12-slim python -c "import secrets; print(secrets.token_urlsafe(64))"

# пароль Postgres
openssl rand -base64 30 | tr -d '/+=' | head -c 32; echo
```

```bash
nano ~/secrets/lesson-tracker.env.prod
```

Заполните так:

```ini
DEBUG=False
SECRET_KEY=<сгенерированный ключ>
ALLOWED_HOSTS=lbreslav.com,www.lbreslav.com

POSTGRES_DB=lessons
POSTGRES_USER=lessons
POSTGRES_PASSWORD=<сгенерированный пароль>
POSTGRES_HOST=db
POSTGRES_PORT=5432

GOOGLE_CLIENT_ID=<из Google Cloud Console>
GOOGLE_CLIENT_SECRET=<из Google Cloud Console>
VITE_GOOGLE_CLIENT_ID=<тот же client_id>

CORS_ALLOWED_ORIGINS=https://lbreslav.com,https://www.lbreslav.com
CSRF_TRUSTED_ORIGINS=https://lbreslav.com,https://www.lbreslav.com

# пока HTTPS нет — всё выключено
SECURE_SSL_REDIRECT=False
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
SECURE_HSTS_SECONDS=0
SECURE_HSTS_INCLUDE_SUBDOMAINS=False
NGINX_SSL=false

# Cloudflare R2: вложения к урокам
R2_ACCESS_KEY_ID=<из R2 → Manage API tokens>
R2_SECRET_ACCESS_KEY=<оттуда же>
R2_BUCKET_NAME=lesson-tracker
R2_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com

# резервный бакет, см. раздел 10; endpoint тот же
R2_BACKUP_BUCKET_NAME=lesson-tracker-backup
R2_BACKUP_ACCESS_KEY_ID=<токен с доступом к обоим бакетам>
R2_BACKUP_SECRET_ACCESS_KEY=<оттуда же>
```

### Как файл попадает на сервер

Его везёт `scripts/sync-env.sh` — тот же скрипт возит файл стенда, и
реализация намеренно одна: две копии одного правила разъезжаются, а
расхождение здесь значит затёртый ключ. `push-deploy.sh` зовёт его до
`deploy.sh`, потому что сборка фронта читает оттуда `VITE_GOOGLE_CLIENT_ID`.

Перед копированием сравнивается sha256 локального и удалённого файла:

* суммы совпали — «`.env.prod` актуален», больше ничего не происходит;
* разошлись — показывает, **какие имена** переменных появились и какие
  исчезли (`+ R2_BACKUP_BUCKET_NAME (новая)`), а если набор имён тот же,
  так и говорит: различаются значения. **Значения не печатаются никогда** —
  ни локальные, ни серверные;
* спрашивает подтверждение, делает на сервере копию `.env.prod.bak.<дата>`
  (хранятся последние три), копирует файл, ставит права `600` и сверяет
  контрольные суммы после копирования.

В самый первый раз, когда на сервере файла ещё нет, всё то же самое — он
просто скажет «на сервере `.env.prod` ещё нет — будет создан». Доставить
файл, **ничего не выкатывая**, можно так:

```bash
./scripts/sync-env.sh prod
./scripts/sync-env.sh staging
```

Здесь раньше стояло `./push-deploy.sh --deploy-only`, и это была ошибка,
стоившая незапланированной выкатки на прод: `--deploy-only` пропускает
**коммит и пуш**, а выкатку как раз делает. Флаг отвечает на вопрос «уже
закоммичено, просто раскатай», а не «только отвези ключи».

Флаг `--skip-env` пропускает этот шаг целиком. Если локального файла нет по
указанному пути, скрипт не падает: предупреждает и оставляет на сервере то,
что там лежит.

### Если всё-таки отредактировали на сервере

Так делать не нужно, но если это уже случилось — **сначала заберите файл
оттуда**, потом правьте локальную копию. Иначе следующая выкатка перезапишет
серверную правку своей версией, и восстанавливать придётся из
`.env.prod.bak.*`.

```bash
# 1. забрать серверную версию к себе
scp leobreslav@194.67.111.40:~/lesson-tracker/.env.prod \
    ~/secrets/lesson-tracker.env.prod

# 2. посмотреть, что там отличается от того, что было
#    (в git этого файла нет, так что сравнивать только глазами)
nano ~/secrets/lesson-tracker.env.prod

# 3. дальше как обычно: правки уезжают вместе с деплоем
./push-deploy.sh --deploy-only
```

Если серверную правку забирать не хочется — просто выкатите с ноутбука:
скрипт покажет расхождение по именам переменных и спросит подтверждение,
а прежняя серверная версия останется в `.env.prod.bak.<дата>`.

**Про бакет.** Он должен быть **приватным** — публичный доступ (r2.dev или
свой домен) включать не нужно и не следует: приложение выдаёт подписанную
ссылку на пять минут, а публичный бакет сделал бы каждую контрольную
доступной по прямому адресу навсегда. Токен заводится с правами
*Object Read & Write* **на один этот бакет**, и он обязан отличаться от
dev-бакета: `seed_demo --flush` чистит свой бакет целиком.

**Второй бакет** — резервный, `lesson-tracker-backup`. Приложение о нём не
знает; в него раз в сутки копирует новые объекты `scripts/backup-files.sh`.
Ему нужен свой токен, с правами *Object Read & Write* **на оба** бакета:
копирование идёт внутри Cloudflare, одним клиентом, и читать источник он
обязан. Подробности и порядок восстановления —
[раздел 10](#10-бэкапы-что-чем-спасается).

`ALLOWED_HOSTS` и `CSRF_TRUSTED_ORIGINS` здесь **без** `localhost` — он нужен
был только для локальной проверки.

---

## 3. Первый запуск

`.env.prod` к этому моменту должен уже лежать на сервере — его доставляет
`./push-deploy.sh --deploy-only` с ноутбука (раздел 2).

```bash
cd ~/lesson-tracker
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```

Сборка фронтенда и установка зависимостей Python занимают несколько минут.
Следите за логами:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f backend
```

Ждём строки `Listening at: http://0.0.0.0:8000`. Миграции и `collectstatic`
выполняются автоматически при старте контейнера.

Состояние сервисов:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml ps -a
```

`frontend-build` должен быть в статусе `Exited (0)` — это одноразовый сборщик,
так и задумано. Остальные три — `Up`.

---

## 4. Суперпользователь

Руками его создавать не нужно — достаточно задать в `.env.prod`:

```
BOOTSTRAP_SUPERUSER_EMAIL=
BOOTSTRAP_SUPERUSER_PASSWORD=
```

Команда выполняется автоматически между `migrate` и `collectstatic`, поэтому
после любого пересоздания базы суперпользователь появляется без ручных шагов.
Она идемпотентна и ничего не удаляет: суперпользователя заводит, только если
его нет **вообще**, — сменить пароль существующему через эти переменные
нельзя. Если адрес уже принадлежит обычному аккаунту (человек успел войти
через Google), аккаунт повышается до суперпользователя, а не дублируется.
Переменные не заданы — шаг пропускается с предупреждением, контейнер
стартует.

Посмотреть, что она сделала:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml -f docker-compose.ssl.yml \
  logs backend | grep -A3 bootstrap
```

Если переменные задавать не хочется, остаётся ручной путь:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml exec backend python manage.py createsuperuser
```

Спросит только email и пароль — поля `username` в модели нет. Подтверждённый
адрес заводится сам (`UserManager._create_user`), поэтому первый вход через
Google не обнулит пароль от админки.

---

## 4а. Школа и её первый администратор

Приложение многошкольное: календарь и курсы принадлежат школе, а расписание
и планы — конкретному учителю. Пользователь без школы войти может, но увидит
только экран «вас не пригласили».

Школы заводит суперпользователь — в интерфейсе, раздел **Школы**. В `/admin/`
за этим ходить не нужно; сам суперпользователь появляется на шаге 4.

1. Войдите через Google под адресом суперпользователя. Школы ещё нет, поэтому
   главная предложит раздел **Школы**.
2. **Школы** → создать школу → «Пригласить администратора» с нужным адресом.
   Приглашённый войдёт через Google и попадёт в школу администратором.
3. Если администратором будете вы сами — пригласите свой же адрес, но сначала
   привяжите себя к школе в `/admin/` (**Accounts → Users** → блок **School**):
   пользователь, у которого школа уже есть, второе приглашение не принимает.
4. Дальше всё из интерфейса: **Школа** → название, курсы, «Учителя» →
   пригласить коллег.

Приглашение ищется по адресу, **подтверждённому Google**, а не по тому, что
человек написал о себе, — иначе чужое приглашение можно было бы присвоить,
вписав себе его адрес.

---

## 5. Проверка по HTTP

```bash
curl -I http://lbreslav.com/
curl -I http://lbreslav.com/admin/login/
curl -s http://lbreslav.com/api/me/
```

Ожидаем `200`, `200` и `{"detail":"Authentication credentials were not provided."}`.

Откройте `http://lbreslav.com` в браузере — должна открыться страница входа.
Кнопка Google пока работать не будет: origin ещё не добавлен в консоли, и
он должен быть `https`. Это делается после выпуска сертификата (шаг 8).

Если что-то не так:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml logs --tail 100 backend nginx
```

---

## 6. HTTPS: сертификат

Certbot ставим **на хост**, а не в контейнер: пакет из apt сам заводит
systemd-таймер продления, и отдельный планировщик не нужен.

```bash
sudo apt update
sudo apt install -y certbot
```

Плагин `python3-certbot-nginx` не нужен: nginx живёт в контейнере, и certbot
не должен править его конфиг. Используем режим `--webroot` — nginx уже отдаёт
`/.well-known/acme-challenge/` из каталога `certbot/www` репозитория.

Сначала прогон вхолостую, он не расходует лимиты Let's Encrypt:

```bash
sudo certbot certonly --webroot \
  -w /home/leobreslav/lesson-tracker/certbot/www \
  -d lbreslav.com -d www.lbreslav.com \
  --email leobreslav@gmail.com --agree-tos --no-eff-email \
  --dry-run
```

Если прошло без ошибок — выпускаем настоящий:

```bash
sudo certbot certonly --webroot \
  -w /home/leobreslav/lesson-tracker/certbot/www \
  -d lbreslav.com -d www.lbreslav.com \
  --email leobreslav@gmail.com --agree-tos --no-eff-email
```

Проверка:

```bash
sudo certbot certificates
sudo ls -l /etc/letsencrypt/live/lbreslav.com/
```

---

## 7. HTTPS: переключение nginx

Конфиг с TLS лежит в `nginx/ssl.conf.template` и подключается оверлеем
`docker-compose.ssl.yml`. Руками ничего править не нужно — достаточно флага.
Правится он **на ноутбуке**, в главной копии (раздел 2):

```bash
nano ~/secrets/lesson-tracker.env.prod
```

```ini
NGINX_SSL=true
```

```bash
./push-deploy.sh --deploy-only
```

`deploy.sh` увидит флаг и поднимет стек с двумя compose-файлами. Проверка:

```bash
curl -I http://lbreslav.com/            # 301 на https
curl -I https://lbreslav.com/           # 200
curl -I https://www.lbreslav.com/       # 200
curl -I https://lbreslav.com/admin/login/
```

### Автопродление

Таймер уже стоит после установки пакета:

```bash
systemctl list-timers certbot.timer
sudo certbot renew --dry-run
```

Осталось добавить хук, который перечитает конфиг nginx в контейнере после
обновления сертификата:

```bash
sudo cp ~/lesson-tracker/scripts/reload-nginx.sh \
        /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
```

Без него nginx продолжит держать в памяти старый сертификат до перезапуска.

---

## 8. Ужесточение настроек

Теперь, когда HTTPS работает — снова в главной копии на ноутбуке:

```bash
nano ~/secrets/lesson-tracker.env.prod
```

```ini
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
```

```bash
./push-deploy.sh --deploy-only
```

Проверьте, что вход в админку по-прежнему работает — `https://lbreslav.com/admin/`.
Если да, включайте HSTS **последним** (браузеры запоминают заголовок на год,
откатить сложно):

```ini
SECURE_HSTS_SECONDS=31536000
```

```bash
./push-deploy.sh --deploy-only
curl -sI https://lbreslav.com/admin/login/ | grep -i strict-transport
```

Контрольная проверка:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml -f docker-compose.ssl.yml \
  exec backend python manage.py check --deploy
```

Должны остаться только `W005` (`SECURE_HSTS_INCLUDE_SUBDOMAINS`) и `W021`
(`SECURE_HSTS_PRELOAD`) — обе про поддомены и preload-список, включать их
необязательно.

---

## 9. Google Cloud Console

**Это нужно сделать руками, иначе кнопка входа не заработает.**

APIs & Services → Credentials → ваш OAuth 2.0 Client ID → **Authorized
JavaScript origins**, добавить:

```
https://lbreslav.com
https://www.lbreslav.com
```

Redirect URI не нужны — вход идёт по frontend-flow с `id_token`.
Изменения вступают в силу в течение нескольких минут.

После этого зайдите на `https://lbreslav.com` и войдите через Google. Ваш
аккаунт свяжется с существующим суперпользователем по email.

---

## 10. Бэкапы: что чем спасается

С появлением вложений данные лежат в **двух** местах, и снапшот VPS
забирает только одно из них.

| что | где живёт | чем спасается |
|---|---|---|
| база: уроки, планы, содержание, ссылки на файлы | Postgres в контейнере на VPS | ежедневный `pg_dump` в `~/backups/` |
| файлы, приложенные к урокам | бакет `lesson-tracker` в Cloudflare R2 | ежедневная синхронизация в бакет `lesson-tracker-backup` |
| собранный фронт, статика Django | том в контейнере | пересобираются из git |

**Второй бакет, а не versioning.** Object versioning — функция AWS S3;
в Cloudflare R2 её нет ни в дашборде, ни в API, и рассчитывать на неё
нельзя. Второй дамп на сам сервер тоже не годится: диск VPS меньше квоты
школы, и его потеря унесла бы обе копии разом. Остаётся копия в отдельном
бакете — там же, где Cloudflare держит оригинал, но за другим именем и
другим токеном.

Копирование **серверное**: у токена резерва есть доступ к обоим бакетам,
поэтому Cloudflare переносит объекты внутри себя. Через сервер не проходит
ни байта, и время работы не зависит от канала VPS.

Резерв — не зеркало. Объект, удалённый в основном бакете, в резервном
**остаётся**: ровно от этого он и защищает. Обратная сторона — резерв
медленно растёт; если это когда-нибудь станет заметно, лишнее выявит
`cleanup_orphaned_files` и удалить его можно будет руками.

Чего эта схема **не** покрывает: удаление аккаунта Cloudflare целиком и
утечку токена резерва — он единственный, кто может писать в обе стороны.
Токен приложения, который лежит в `.env.prod` рядом, о резервном бакете не
знает вовсе.

### Расписание

Обе задачи — в crontab пользователя, со сдвигом по времени: одновременно
им работать незачем. Логи разные — база пишет каждый день по три строки, а
синхронизация файлов молчит, пока копировать нечего, и в общем логе её
нечастые строки терялись бы.

```bash
mkdir -p ~/backups
crontab -e
```

```cron
30 3 * * * /home/leobreslav/lesson-tracker/scripts/backup-db.sh >> /home/leobreslav/backups/backup.log 2>&1
0 4 * * * /home/leobreslav/lesson-tracker/scripts/backup-files.sh >> /home/leobreslav/backups/files.log 2>&1
0 5 * * 1 /home/leobreslav/lesson-tracker/scripts/check-orphaned-files.sh >> /home/leobreslav/backups/orphans.log 2>&1
```

Третья строка — не копия, а сверка: раз в неделю ищет расхождения между
бакетом и базой и **ничего не удаляет**. Сирот в норме не бывает вовсе, но
обе половины обычного удаления умеют падать (объект без записи — откат
транзакции после загрузки; запись без ссылок — отказ R2 в момент сноса), и
заметить это было нечем. Лог пустой, пока всё в порядке: команда идёт с
`--quiet`. Появились строки — смотреть руками и, если это правда мусор,
повторить с `--delete`.

Проверьте оба сразу, не дожидаясь ночи:

```bash
~/lesson-tracker/scripts/backup-db.sh
~/lesson-tracker/scripts/backup-files.sh --dry-run
~/lesson-tracker/scripts/check-orphaned-files.sh
ls -lh ~/backups/lesson-tracker/
tail ~/backups/backup.log ~/backups/files.log
```

### База: дампы

`scripts/backup-db.sh` кладёт `pg_dump | gzip` в `~/backups/lesson-tracker/`
и хранит копии 7 дней. Старое удаляется только после удачного дампа, иначе
неудачный запуск постепенно съел бы весь архив.

Восстановление:

```bash
cd ~/lesson-tracker
gunzip -c ~/backups/lesson-tracker/lessons_ГГГГ-ММ-ДД_ЧЧММ.sql.gz \
  | docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T db \
      psql -U lessons -d lessons
```

Дамп снимается с `--clean --if-exists`, поэтому заливается поверх
существующей базы. Копии лежат на том же сервере — от потери диска они не
спасают; если это важно, стоит настроить выгрузку наружу.

### Файлы: синхронизация в резервный бакет

`scripts/backup-files.sh` печатает итог вида
`скопировано: 3, пропущено (уже есть): 128, осталось только в резерве: 2`.
Повторный запуск ничего не портит, пустой бакет не ошибка, `--dry-run`
показывает список, ничего не копируя.

Под капотом — `manage.py backup_files` внутри контейнера backend: питон с
boto3 и ключи там уже есть, ставить на хост `aws-cli` ради этого незачем.
Сравнение идёт по размеру и etag, так что ночной прогон по нетронутому
бакету — это два листинга и никакого трафика.

Восстановление — та же синхронизация в обратную сторону: чего в основном
бакете нет, возвращается из резервного; что есть — не трогается.

```bash
cd ~/lesson-tracker
./scripts/backup-files.sh --restore --dry-run   # сначала посмотреть
./scripts/backup-files.sh --restore             # и только потом
```

Годится и для одного случайно удалённого файла, и для пустого бакета
целиком — команда одна и та же, разница только в числе объектов.

### Когда база и бакет разошлись

Восстановление базы из дампа **не** трогает R2, и наоборот: вернуть объект
не значит вернуть ссылку на него. После отката любой из сторон стоит
посмотреть, что разошлось:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml exec backend \
  python manage.py cleanup_orphaned_files
```

Она печатает объекты без записи и записи без вложений; удаляет только с
`--delete`. Штатно она не находит ничего — см. `backend/files/signals.py`.

**Порядок при полной потере**: сначала база из дампа, потом файлы
(`--restore`), потом `cleanup_orphaned_files` без `--delete` — он и покажет,
насколько дамп оказался старше последней синхронизации. Записи без объекта
означают, что дамп новее файлов: эти вложения придётся удалить руками или
загрузить заново.

---

## Переход на многошкольную модель (одноразовый шаг)

История миграций пересобрана с нуля: `owner` у года и курса заменён на
`school`, а у слотов и планов появился `teacher`. Мигрировать старые данные
некуда — они были тестовыми, — поэтому **база сносится**:

```bash
ssh leobreslav@194.67.111.40
cd ~/lesson-tracker
docker compose --env-file .env.prod -f docker-compose.prod.yml -f docker-compose.ssl.yml down
docker volume rm lesson-tracker-prod_pgdata
./deploy.sh
```

Дальше — заново: `createsuperuser`, школа и администратор по разделу 4а выше.

На пустой базе миграции применяются сами, никаких ручных шагов не нужно;
проверено `docker compose down -v` + `migrate` с нуля.

---

## Обновление кода потом

С ноутбука одной командой — коммит, пуш и деплой на сервере:

```bash
./push-deploy.sh "что поменялось"
./push-deploy.sh --deploy-only     # передеплой без новых коммитов
./push-deploy.sh --no-verify "…"   # не проверять сайт после деплоя
```

`push-deploy.sh` не даст задеплоить не из корня репозитория, не с ветки
`main` и с секретами (`.env`, `.env.prod`, ключи) в рабочем дереве, а после
деплоя дёргает `https://lbreslav.com/` и показывает код ответа. Сообщение
коммита можно не передавать — скрипт спросит. По дороге он ещё
синхронизирует `.env.prod` с ноутбука (раздел 2); пропустить этот шаг —
`--skip-env`.

Руками то же самое:

```bash
ssh leobreslav@194.67.111.40
cd ~/lesson-tracker
./deploy.sh
```

Разница одна: `deploy.sh` знает только про git, поэтому `.env.prod` при
таком запуске остаётся тем, что уже лежит на сервере — новые переменные
приезжают только с ноутбука.

`deploy.sh` откажется работать, если в рабочем дереве на сервере есть
локальные правки — конфиги на сервере руками не редактируем, всё через git
и `.env.prod` (он приезжает копированием и лежит в `.gitignore`).

## Полезные команды

```bash
cd ~/lesson-tracker
C="docker compose --env-file .env.prod -f docker-compose.prod.yml -f docker-compose.ssl.yml"

$C ps -a
$C logs -f backend
$C exec backend python manage.py createsuperuser
$C exec db psql -U lessons -d lessons
$C restart backend
$C down                    # погасить, данные в томах останутся
```

При `NGINX_SSL=false` второй `-f` не нужен.
