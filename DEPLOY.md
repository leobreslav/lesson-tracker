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

```bash
cd ~/lesson-tracker
cp .env.prod.example .env.prod
```

Сгенерируйте два секрета — **не переиспользуйте dev-значения**:

```bash
# SECRET_KEY
docker run --rm python:3.12-slim python -c "import secrets; print(secrets.token_urlsafe(64))"

# пароль Postgres
openssl rand -base64 30 | tr -d '/+=' | head -c 32; echo
```

```bash
nano .env.prod
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
R2_BUCKET_NAME=lesson-tracker-prod
R2_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
```

```bash
chmod 600 .env.prod
```

**Про бакет.** Он должен быть **приватным** — публичный доступ (r2.dev или
свой домен) включать не нужно и не следует: приложение выдаёт подписанную
ссылку на пять минут, а публичный бакет сделал бы каждую контрольную
доступной по прямому адресу навсегда. Токен заводится с правами
*Object Read & Write* **на один этот бакет**, и он обязан отличаться от
dev-бакета: `seed_demo --flush` чистит свой бакет целиком.

Отдельно включите versioning — см. [раздел 10](#10-бэкапы-что-чем-спасается).

`ALLOWED_HOSTS` и `CSRF_TRUSTED_ORIGINS` здесь **без** `localhost` — он нужен
был только для локальной проверки.

---

## 3. Первый запуск

```bash
cd ~/lesson-tracker
docker compose -f docker-compose.prod.yml up -d --build
```

Сборка фронтенда и установка зависимостей Python занимают несколько минут.
Следите за логами:

```bash
docker compose -f docker-compose.prod.yml logs -f backend
```

Ждём строки `Listening at: http://0.0.0.0:8000`. Миграции и `collectstatic`
выполняются автоматически при старте контейнера.

Состояние сервисов:

```bash
docker compose -f docker-compose.prod.yml ps -a
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
docker compose -f docker-compose.prod.yml -f docker-compose.ssl.yml \
  logs backend | grep -A3 bootstrap
```

Если переменные задавать не хочется, остаётся ручной путь:

```bash
docker compose -f docker-compose.prod.yml exec backend python manage.py createsuperuser
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
docker compose -f docker-compose.prod.yml logs --tail 100 backend nginx
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

Конфиг с TLS лежит в `nginx/ssl.conf` и подключается оверлеем
`docker-compose.ssl.yml`. Руками ничего править не нужно — достаточно флага:

```bash
cd ~/lesson-tracker
nano .env.prod
```

```ini
NGINX_SSL=true
```

```bash
./deploy.sh
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

Теперь, когда HTTPS работает:

```bash
nano .env.prod
```

```ini
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
```

```bash
./deploy.sh
```

Проверьте, что вход в админку по-прежнему работает — `https://lbreslav.com/admin/`.
Если да, включайте HSTS **последним** (браузеры запоминают заголовок на год,
откатить сложно):

```ini
SECURE_HSTS_SECONDS=31536000
```

```bash
./deploy.sh
curl -sI https://lbreslav.com/admin/login/ | grep -i strict-transport
```

Контрольная проверка:

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.ssl.yml \
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
| база: уроки, планы, содержание, ссылки на файлы | Postgres в контейнере на VPS | ежедневный `pg_dump`, ниже |
| файлы, приложенные к урокам | бакет Cloudflare R2 | **versioning на бакете** |
| собранный фронт, статика Django | том в контейнере | пересобираются из git |

**Versioning, а не второй дамп.** Выгружать бакет ночью на тот же сервер
означало бы держать копию файлов ровно там, где их и так нет смысла держать:
диск VPS меньше квоты школы, и потеря диска унесла бы обе копии сразу.
Versioning решает ту задачу, ради которой бэкап файлов вообще нужен —
восстановить объект, удалённый по ошибке, — и делает это на стороне
Cloudflare, вне досягаемости чего угодно, что случится с сервером.

Включается один раз, в консоли Cloudflare: **R2 → бакет → Settings →
Object versioning → Enable**. Там же стоит завести правило жизненного цикла
(*Delete previous versions after 30 days*), иначе удалённые версии копятся
вечно.

Что versioning **не** покрывает: удаление самого бакета и утечку ключа с
правами на запись. Ключи в `.env.prod` — с доступом только к одному бакету,
и это тот случай, когда узкий токен важнее удобства.

Ссылки в базе и объекты в бакете могут разойтись, если восстанавливать
только одну сторону. Расхождение видно командой:

```bash
docker compose -f docker-compose.prod.yml exec backend \
  python manage.py cleanup_orphaned_files
```

Она печатает объекты без записи и записи без вложений; удаляет только с
`--delete`. Штатно она не находит ничего — см. `backend/files/signals.py`.

### Дампы базы

```bash
mkdir -p ~/backups
crontab -e
```

Добавьте строку:

```cron
30 3 * * * /home/leobreslav/lesson-tracker/scripts/backup-db.sh >> /home/leobreslav/backups/backup.log 2>&1
```

Дампы падают в `~/backups/lesson-tracker/`, хранятся 7 дней.

Проверьте сразу, не дожидаясь ночи:

```bash
~/lesson-tracker/scripts/backup-db.sh
ls -lh ~/backups/lesson-tracker/
```

Восстановление из дампа:

```bash
cd ~/lesson-tracker
gunzip -c ~/backups/lesson-tracker/lessons_ГГГГ-ММ-ДД_ЧЧММ.sql.gz \
  | docker compose -f docker-compose.prod.yml exec -T db \
      psql -U lessons -d lessons
```

Дамп снимается с `--clean --if-exists`, поэтому заливается поверх
существующей базы. Копии лежат на том же сервере — от потери диска они не
спасают; если это важно, стоит настроить выгрузку наружу.

Восстановление базы из дампа **не** трогает R2: ссылки на файлы вернутся в
том виде, в каком были на момент дампа, а объекты в бакете никуда и не
девались. Обратное тоже верно — восстановление объекта из версии не создаёт
ссылку на него. После отката базы стоит прогнать `cleanup_orphaned_files`
без `--delete` и посмотреть, что разошлось.

---

## Переход на многошкольную модель (одноразовый шаг)

История миграций пересобрана с нуля: `owner` у года и курса заменён на
`school`, а у слотов и планов появился `teacher`. Мигрировать старые данные
некуда — они были тестовыми, — поэтому **база сносится**:

```bash
ssh leobreslav@194.67.111.40
cd ~/lesson-tracker
docker compose -f docker-compose.prod.yml -f docker-compose.ssl.yml down
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
коммита можно не передавать — скрипт спросит.

Руками то же самое:

```bash
ssh leobreslav@194.67.111.40
cd ~/lesson-tracker
./deploy.sh
```

`deploy.sh` откажется работать, если в рабочем дереве на сервере есть
локальные правки — конфиги на сервере руками не редактируем, всё через git
и `.env.prod` (он в `.gitignore`).

## Полезные команды

```bash
cd ~/lesson-tracker
C="docker compose -f docker-compose.prod.yml -f docker-compose.ssl.yml"

$C ps -a
$C logs -f backend
$C exec backend python manage.py createsuperuser
$C exec db psql -U lessons -d lessons
$C restart backend
$C down                    # погасить, данные в томах останутся
```

При `NGINX_SSL=false` второй `-f` не нужен.
