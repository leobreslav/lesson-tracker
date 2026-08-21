---
paths:
  - "deploy.sh"
  - "push-deploy.sh"
  - "docker-compose.prod.yml"
  - "docker-compose.ssl.yml"
  - "docker-compose.yml"
  - "nginx/**"
  - "scripts/**"
  - ".env.prod.example"
  - "backend/Dockerfile"
  - "frontend/Dockerfile"
---

## Боевая конфигурация

`docker-compose.prod.yml`, переменные в `.env.prod` (шаблон —
`.env.prod.example`; сам файл в проекте не лежит, см. ниже про три
env-файла). Первое развёртывание на сервер описано в
[DEPLOY.md](../../DEPLOY.md), последующие обновления — `./push-deploy.sh "текст
коммита"` с ноутбука: он коммитит, пушит, запускает `deploy.sh` на сервере
по ssh и проверяет, что сайт отвечает 200. Флаги: `--deploy-only` (только
раскатать), `--no-verify` (без проверки сайта) и `--skip-env` (не трогать
`.env.prod`). Перед стартом скрипт проверяет, что мы в корне репозитория, на
ветке `main` и что в рабочем дереве нет секретов — `git add -A` иначе
утащил бы их в коммит. На самом сервере всё то же делает `./deploy.sh`.

### Кто хозяин .env.prod

Главная копия — **на ноутбуке, вне репозитория**
(`~/secrets/lesson-tracker.env.prod`, путь меняется `DEPLOY_ENV_FILE`).
В git файл попасть не может, значит, на сервер он приезжает копированием, а
раз копирование одностороннее, у файла должен быть один хозяин: иначе
выкатка однажды затрёт правку, сделанную на сервере. Поэтому на сервере его
руками не редактируют, а `push-deploy.sh` отказывается работать, если
локальный файл лежит внутри репозитория.

Синхронизация идёт **до** `deploy.sh`: сборка фронта читает оттуда
`VITE_GOOGLE_CLIENT_ID`. Сравниваются sha256; при расхождении показываются
только **имена** появившихся и исчезнувших переменных — значения не
печатаются ни при каких обстоятельствах, там пароль базы и токены R2.
Дальше подтверждение, копия `.env.prod.bak.<дата>` на сервере (хранятся три,
и они в `.gitignore` — иначе `deploy.sh` счёл бы дерево грязным) и `chmod
600`. Нет локального файла — предупреждение и пропуск шага, а не отказ.

### Три env-файла и почему они разные

| файл | для чего | `DEBUG` | бакет R2 |
|---|---|---|---|
| `~/projects/lesson-tracker/.env` | разработка: runserver, Vite, `seed_demo` | `True` | dev |
| `~/secrets/lesson-tracker.env.local-prod` | прод-сборка на `http://localhost` | `False` | dev |
| `~/secrets/lesson-tracker.env.prod` | боевой; копия серверного | `False` | **прод** |

Совпадают у них только ключи Google: клиент один, `http://localhost` есть в
разрешённых origins. `SECRET_KEY`, пароль базы и токены R2 — разные, и это
не гигиена ради гигиены: `seed_demo --flush` чистит бакет целиком, поэтому
один запуск не с тем файлом стоил бы школе всех вложений. Отсюда правило:
**боевой бакет подключается только на сервере**, у локального прод-стека
dev-бакет.

Набор имён переменных у `local-prod` и боевого одинаковый — так видно, что
локальная проверка гоняет ту же конфигурацию, а не её огрызок. Различия
только в значениях: `localhost` в хостах и origins, `NGINX_SSL=false`,
выключенные secure-куки и HSTS (сертификата на localhost нет, а
`SECURE_SSL_REDIRECT` увёл бы проверку в https), пустые `R2_BACKUP_*` —
резерв локально не гоняем, и `backup_files` без них честно откажется
работать.

Прод-стек читает `env_file: .env.prod` и другого имени не знает, поэтому на
время проверки файл кладут в корень проекта копией, а потом убирают:

```bash
cp ~/secrets/lesson-tracker.env.local-prod .env.prod
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
docker compose --env-file .env.prod -f docker-compose.prod.yml down && rm .env.prod
```

`--env-file` тут обязателен: из него compose берёт `DOMAIN` и
`COMPOSE_PROJECT_NAME` для подстановки в сами compose-файлы. Без флага
compose ищет `.env`, не находит `DOMAIN` и честно отказывается —
молча подняться с пустым `server_name` он не может.

Он поднимается рядом с dev — своё имя проекта, свои порты 80/443. В пустой
базе школы нет и войти некуда, поэтому в файле лежит закомментированная
пара `BOOTSTRAP_SUPERUSER_*`: раскомментировать — и будет доступ в
`/admin/`.

HTTPS включается одним флагом `NGINX_SSL=true` в `.env.prod`: `deploy.sh`
добавляет оверлей `docker-compose.ssl.yml`, который подменяет шаблон nginx
на `nginx/ssl.conf.template` и прокидывает `/etc/letsencrypt`. Конфиг с TLS —
отдельный файл, а не закомментированный блок, потому что правка
шаблона руками на сервере сломала бы `git pull` в `deploy.sh`.
Сертификаты выпускает certbot **на хосте** (`certonly --webroot`), продление
делает его systemd-таймер, а `scripts/reload-nginx.sh` в
`/etc/letsencrypt/renewal-hooks/deploy/` перечитывает конфиг в контейнере.

```bash
C="docker compose --env-file .env.prod -f docker-compose.prod.yml"
$C up -d --build
$C logs -f backend
$C down
```

Отличия от dev:

- backend — `gunicorn config.wsgi:application --workers 2`, стадия `prod`
  Dockerfile; код зашит в образ, bind-mount'а нет. При старте выполняются
  `migrate --noinput` и `collectstatic --noinput`.
- `db` не публикует порт наружу — до неё дотягивается только backend.
- `frontend-build` — одноразовый контейнер: `npm ci && npm run build`, кладёт
  бандл в том `frontend_dist` и завершается. nginx ждёт его через
  `condition: service_completed_successfully`.
- nginx раздаёт `frontend_dist` (с fallback на `index.html`) и `static_files`
  по `/static/`, проксирует `/api/` и `/admin/` на `backend:8000`.

Что стоит помнить:

- У prod-стека **своё имя проекта** — `${COMPOSE_PROJECT_NAME:-lesson-tracker-prod}`.
  Без него compose взял бы имя каталога, как у dev, и переиспользовал его
  контейнеры и том с базой. Умолчание оставлено прежним намеренно: env-файл
  без этой переменной обязан дать тот же проект, иначе стек молча получил бы
  новые тома и пустую базу.
- **Внутрь контейнеров** переменные приходят через `env_file: .env.prod`.
  А для `${...}` в самих compose-файлах — имя проекта и `DOMAIN` — тот же
  файл передаётся флагом `--env-file`: по умолчанию compose искал бы `.env`,
  которого в проде нет. Раньше `${...}` не использовался вовсе именно
  поэтому.
  В healthcheck по-прежнему `$$POSTGRES_USER` — его разворачивает шелл
  контейнера, а не compose.
- **Домена в репозитории не осталось.** `nginx/*.conf.template` прогоняются
  через `envsubst` при старте контейнера, `DOMAIN` и `DOMAIN_ALIASES` берутся
  из env-файла. `NGINX_ENVSUBST_FILTER` ограничивает подстановку этими двумя
  именами — без фильтра `envsubst` подставил бы и `$host`, `$uri`,
  `$backend_addr`, то есть переменные самого nginx, и конфиг сломался бы
  молча. `deploy.sh` отказывается работать без `DOMAIN` **до** `git pull`:
  пустой `server_name` уронил бы nginx уже после пересборки.
- `VITE_GOOGLE_CLIENT_ID` нужен **на этапе сборки** фронта: Vite вшивает его
  в бандл. Меняется — нужно пересобрать `frontend-build`.
- **Адрес backend'а nginx держит в переменной** (`set $backend_addr backend:8000;`
  плюс `resolver 127.0.0.11 valid=10s ipv6=off;`), а не в блоке `upstream`.
  Имя в `upstream` резолвится один раз при старте: после пересоздания
  контейнера backend получает новый IP, а nginx продолжает ходить на старый и
  отдаёт 502 до перезапуска. С переменной имя перечитывается по TTL. Обратная
  сторона — `proxy_pass` с переменной не делает подстановку URI, но у нас в
  `proxy_pass` и не было пути, так что запрос уходит без изменений.
- nginx объявлен `default_server`, поэтому отвечает на любой Host (это нужно
  для проверки по `http://localhost`). Django при этом свой `ALLOWED_HOSTS`
  проверяет: запрос к `/api/` с чужим Host получает 400.
- `manage.py check --deploy` на проде показывает **одно** предупреждение —
  `SECURE_HSTS_SECONDS`. Остальные три (`SECURE_SSL_REDIRECT`,
  `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`) читаются из env и включены
  с тех пор, как на сервере появились сертификаты. HSTS оставлен нулём
  сознательно: включается он легко, а выключается только по истечении срока
  у каждого браузера, который его запомнил.
