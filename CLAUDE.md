# lesson-tracker

Трекер количества проведённых уроков в учебном году для школьного учителя.
Учитель ведёт учёт по классам/предметам и видит, сколько уроков проведено
относительно плана на год.

Прод: VPS Ubuntu 24.04, домен `lbreslav.com`.
Репозиторий: `git@github.com:leobreslav/lesson-tracker.git`.

## Стек

- **Backend**: Django 5.1, DRF 3.15, Postgres 16 (psycopg 3), gunicorn
- **Аутентификация**: django-allauth 65 + dj-rest-auth 7 + TokenAuthentication
- **Frontend**: React 19 + Vite 8 (dev-сервер на `http://localhost:5173`), без роутера
- **Инфраструктура**: Docker Compose; конфиг через django-environ из `.env` в корне

## Структура

```
.
├── docker-compose.yml        # dev: db + backend (runserver) + frontend (vite)
├── docker-compose.prod.yml   # prod: db + gunicorn + сборка фронта + nginx
├── .env / .env.example       # dev-окружение
├── .env.prod / .env.prod.example
├── nginx/
│   ├── default.conf          # server_name lbreslav.com, www.lbreslav.com
│   └── proxy_params.conf     # заголовки для проксирования на backend
├── backend/
│   ├── Dockerfile            # python:3.12-slim, стадии base/dev/prod
│   ├── requirements.txt
│   ├── config/               # settings.py, urls.py, wsgi.py, asgi.py
│   └── accounts/             # кастомный User + аутентификация
│       ├── models.py         # User(AbstractUser) + UserManager
│       ├── admin.py          # UserAdmin без username
│       ├── adapter.py        # SocialAccountAdapter: только верифицированные email
│       ├── serializers.py    # GoogleLoginSerializer, UserSerializer
│       ├── views.py          # GoogleLoginView, MeView
│       ├── urls.py
│       └── tests.py          # тесты входа через Google (подпись подменяется mock'ом)
└── frontend/
    ├── Dockerfile            # node:22-alpine, npm ci
    ├── vite.config.js        # host 0.0.0.0, прокси /api -> backend:8000
    ├── .env                  # VITE_GOOGLE_CLIENT_ID, в git не попадает
    ├── index.html            # подключает скрипт GIS
    └── src/
        ├── App.jsx           # выбор экрана по наличию токена
        ├── Login.jsx         # кнопка Google Identity Services
        ├── Dashboard.jsx     # email из /api/me/ + выход
        ├── api.js            # fetch-обёртка, токен в localStorage
        └── styles.css
```

Модели самого трекера (классы, предметы, уроки) ещё не написаны — они
делаются в последнюю очередь, после фронтенда и деплоя.

## Команды разработки

Все команды Django выполняются внутри контейнера:

```bash
docker compose up -d                                  # поднять всё
docker compose exec backend python manage.py <cmd>    # любая команда Django
docker compose exec backend python manage.py test accounts
docker compose build backend                          # после правки requirements.txt
docker compose up -d --force-recreate backend         # подхватить новый образ
docker compose logs -f backend
docker compose down -v                                # снести вместе с данными БД
```

Backend слушает `http://localhost:8000`, frontend — `http://localhost:5173`.
Код примонтирован томами (`./backend:/app`, `./frontend:/app`), runserver и
Vite перезапускаются сами — пересборка нужна только при изменении зависимостей.

`node_modules` лежат в именованном томе, а не в bind-mount: пакеты ставятся
под alpine и не должны смешиваться с хостовыми. Поэтому после правки
`package.json` нужно пересобрать образ **и** пересоздать том:

```bash
docker compose build frontend
docker compose down && docker volume rm lesson-tracker_node_modules
docker compose up -d
```

`package-lock.json` обновляется без установки пакетов на хост:

```bash
cd frontend && docker run --rm -v "$PWD:/app" -w /app --user "$(id -u):$(id -g)" \
  node:22-alpine npm install --package-lock-only
```

## Особенности окружения

- Разработка в **WSL2 Ubuntu**.
- **Файлы, созданные контейнером, принадлежат root.** После `startapp`,
  `makemigrations` и подобного нужно:
  ```bash
  sudo chown -R $USER:$USER backend
  ```
  Команда требует пароль, поэтому её запускает пользователь вручную.
- `createsuperuser` интерактивна — тоже запускается пользователем.
- `settings.py` читает `BASE_DIR / ".env"`, то есть `/app/.env`, которого
  нет; переменные реально приходят из `env_file: .env` в compose. Вне
  контейнера `manage.py` без экспорта переменных не заработает.

## Аутентификация

Пользователь опознаётся по **email**, поля `username` нет:
`accounts.User(AbstractUser)` с `username = None`, `USERNAME_FIELD = "email"`,
`REQUIRED_FIELDS = []` и своим `UserManager`. `AUTH_USER_MODEL = "accounts.User"`.

Схема входа — **frontend-flow**: React получает `id_token` от Google Identity
Services и шлёт его на бэкенд; бэкенд проверяет подпись по ключам Google.
Redirect URI на стороне Django не используются.

Ключи Google берутся из `.env` и подставляются в
`SOCIALACCOUNT_PROVIDERS["google"]["APP"]` — `SocialApp` в админке заводить
не нужно. Фронтенд берёт тот же client_id из `frontend/.env`
(`VITE_GOOGLE_CLIENT_ID`); origin `http://localhost:5173` должен быть в списке
разрешённых в консоли Google Cloud, иначе кнопка GIS не отрисуется.

Включён `SOCIALACCOUNT_EMAIL_AUTHENTICATION`: вход через Google подхватывает
существующий локальный аккаунт с тем же адресом. allauth делает это только
для адресов, которые провайдер отдал подтверждёнными (`email_verified` в
id_token), см. `adapter.authenticate_by_email`.

### Эндпоинты

| Метод | URL | Описание |
|---|---|---|
| POST | `/api/auth/google/` | `{"id_token": ...}` или `{"access_token": ...}` → `{"key": "<токен DRF>"}`; при первом входе пользователь создаётся по email |
| POST | `/api/auth/logout/` | удаляет токен; требует заголовок `Authorization` |
| GET | `/api/me/` | `id`, `email`, `first_name`, `last_name` |

Запросы к API авторизуются заголовком `Authorization: Token <ключ>`.
`DEFAULT_PERMISSION_CLASSES = IsAuthenticated` — все новые вьюхи закрыты
по умолчанию.

Вход по паролю в `/admin/` продолжает работать: в
`AUTHENTICATION_BACKENDS` оставлен `ModelBackend` рядом с бэкендом allauth.

### Подводные камни, уже разобранные

- Штатный `SocialLoginSerializer` из dj-rest-auth требует `access_token`
  или `code` и падает на «голом» `id_token`. `GoogleLoginSerializer`
  копирует `id_token` в `access_token`; дальше dj-rest-auth сам передаёт
  адаптеру `response={"id_token": ...}`, а `GoogleOAuth2Adapter` проверяет
  подпись, потому что `did_fetch_access_token` остаётся `False`.
- Битый `id_token` поднимает `OAuth2Error`, который dj-rest-auth не ловит,
  и превращается в 500. `GoogleLoginSerializer` перехватывает его и
  возвращает 400.
- В `UserAdmin` обязателен `ordering = ("email",)` — дефолтный ordering
  ссылается на несуществующий `username` и даёт `admin.E033`.
- В `add_fieldsets` нужно поле `usable_password`: Django 5.1 добавил его в
  `AdminUserCreationForm`, без него админка падает с `FieldError`.
- При email-аутентификации allauth вызывает `wipe_password` и делает пароль
  непригодным, если у локального пользователя **нет подтверждённой записи
  `EmailAddress`**. `createsuperuser` такую запись не создаёт, поэтому первый
  вход через Google обнулил бы пароль от `/admin/`. Миграция
  `accounts/0002_verified_email_addresses` заводит `EmailAddress(verified=True)`
  для существующих пользователей; для новых аккаунтов, заводимых вручную,
  запись нужно создавать самому.
- Неподтверждённый адрес от провайдера allauth уводит на HTML-форму
  `socialaccount_signup`, которой в SPA нет — получался `NoReverseMatch` и 500.
  `accounts/adapter.py` отсекает такой вход, серилизатор отдаёт 400.
- Прокси Vite настроен **без** `changeOrigin`: с ним Host становится
  `backend:8000` и Django отвечает `DisallowedHost`.

## Боевая конфигурация

`docker-compose.prod.yml`, переменные в `.env.prod` (шаблон —
`.env.prod.example`). Проверена локально на `http://localhost`; на сервер ещё
не выкатывалась, HTTPS не настроен.

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs -f backend
docker compose -f docker-compose.prod.yml down
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

- У prod-стека **своё имя проекта** (`name: lesson-tracker-prod`). Без него
  compose взял бы имя каталога — как у dev — и переиспользовал его контейнеры
  и том с базой. Благодаря разным именам оба стека можно держать поднятыми
  одновременно.
- Переменные в prod-compose приходят через `env_file: .env.prod`, а не через
  `${...}`: подстановка compose читает `.env`, которого в проде не будет.
  В healthcheck по той же причине `$$POSTGRES_USER` — разворачивает шелл
  контейнера, а не compose.
- `VITE_GOOGLE_CLIENT_ID` нужен **на этапе сборки** фронта: Vite вшивает его
  в бандл. Меняется — нужно пересобрать `frontend-build`.
- nginx объявлен `default_server`, поэтому отвечает на любой Host (это нужно
  для проверки по `http://localhost`). Django при этом свой `ALLOWED_HOSTS`
  проверяет: запрос к `/api/` с чужим Host получает 400.
- `manage.py check --deploy` показывает 4 предупреждения — все про HTTPS
  (`SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`,
  `SECURE_HSTS_SECONDS`). Все четыре читаются из env и включаются
  переключением в `.env.prod`, когда на сервере появятся сертификаты.

## Фронтенд

Роутера нет: `App.jsx` держит токен в `useState` (инициализируется из
`localStorage`) и по его наличию показывает `Login` либо `Dashboard`.
`Dashboard` при 401 от `/api/me/` сбрасывает токен и возвращает на логин.

Запросы идут на относительный `/api/...` — в dev их проксирует Vite, так что
CORS в разработке фактически не задействован (настройки всё равно нужны для
прода, где фронт и API будут на разных origin).

## Дальнейшие планы

1. Деплой на VPS: раскомментировать 443-й server-блок в `nginx/default.conf`,
   выпустить сертификаты certbot'ом, включить `SECURE_SSL_REDIRECT`,
   `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, затем `SECURE_HSTS_SECONDS`.
   В консоли Google Cloud добавить origin `https://lbreslav.com`.
2. Модели трекера уроков и API к ним.
