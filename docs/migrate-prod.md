# Переезд прода на новый сервер

Пошаговый план переноса боевого контура `lbreslav.com` вместе с базой на
новую машину. Написан под DigitalOcean (Ubuntu 24.04, 2 vCPU, 2 GB), но от
хостера здесь зависят только первые шаги.

Ниже `OLD` — старый сервер (`194.67.111.40`), `NEW` — новый (его IP подставьте
сами). Команды помечены тем, где их выполнять: **ноутбук**, **NEW**, **OLD**.

## Что переезжает и что нет

| что | как | откуда |
|---|---|---|
| код | `git clone`, ветка `production` | GitHub |
| `.env.prod` | `./scripts/sync-env.sh prod` | ноутбук, `~/secrets/` |
| база Postgres | `pg_dump` → `psql` | OLD → ноутбук → NEW |
| сертификаты Let's Encrypt | архив `/etc/letsencrypt` | OLD → ноутбук → NEW |
| вложения | **не переезжают**: они в R2, бакет тот же | — |
| crontab: автовыкатка, два бэкапа | ставится заново | `DEPLOY.md` |
| DNS `lbreslav.com`, `www` | A-записи на NEW | панель DNS |

Ничего не меняется в Google Cloud Console (origins по домену), в R2, в
ключах Anthropic и в SMTP: всё это живёт в `.env.prod`, а файл едет как есть.

## Короткий путь, если простой не страшен

Пока пользователи прода это мы сами, непрерывность не нужна, и план
сжимается до одного прохода. Шаги ниже по номерам разделов этого файла:

1. Сервер: пользователь, docker, своп, ufw. Раздел 1.
2. Deploy key, клон, ветка `production`. Раздел 2.
3. **Остановить OLD сразу**: `crontab -r` и `stop backend` из раздела 7.
   База с этого момента не меняется, и дамп можно снимать когда угодно.
4. Сертификаты архивом и `.env.prod` через `sync-env.sh`. Разделы 3 и 4.
5. Первый подъём стека на NEW, пока с пустой базой. Конец раздела 4.
6. Дамп с OLD и заливка на NEW. Блок команд раздела 5, один раз.
7. DNS на NEW, подождать, открыть сайт, войти. Конец раздела 7.
8. Crontab, продление, правка `contours.sh` и прозы. Раздел 8.

Выпадают TTL (раздел 0), репетиция (раздел 5 как отдельный шаг) и проверка
в обход DNS (раздел 6). Порядок «стек на NEW отвечает 200 по
`https://localhost`, и только потом DNS» стоит сохранить: упавшая сборка
тогда не удлиняет простой.

## Порядок без простоя

Подготовить NEW целиком на **копии** базы, проверить его по домену в обход
DNS, и только потом короткое окно: остановить запись на OLD, снять свежий
дамп, залить, переключить DNS. Окно занимает минуты, а всё до него можно
делать не спеша, школа этого не видит.

---

## 0. За день до переезда: TTL у DNS

**Панель DNS.** Уменьшите TTL у A-записей `lbreslav.com` и `www.lbreslav.com`
до 300 секунд. Тогда в день переезда браузеры увидят новый адрес за пять
минут, а не за час. Обратно поднимать не обязательно.

## 1. Свежий сервер: пользователь, docker, своп

Дроплет создаётся с доступом под `root`, а весь репозиторий написан под
пользователя `leobreslav` в его домашнем каталоге. Заводим его первым делом.

**NEW, под root:**

```bash
adduser --disabled-password --gecos "" leobreslav
usermod -aG sudo leobreslav
echo 'leobreslav ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/leobreslav
mkdir -p /home/leobreslav/.ssh
cp /root/.ssh/authorized_keys /home/leobreslav/.ssh/
chown -R leobreslav:leobreslav /home/leobreslav/.ssh
chmod 700 /home/leobreslav/.ssh && chmod 600 /home/leobreslav/.ssh/authorized_keys
```

Проверьте с ноутбука, что вход работает: `ssh leobreslav@NEW`. Дальше всё
под этим пользователем.

**NEW:**

```bash
# docker из официального репозитория, с плагином compose
sudo apt update && sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin certbot
sudo usermod -aG docker "$USER"

# своп на 1 GB: страховка от пика сборки фронтенда
sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# файрвол: только ssh, http, https
sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
sudo ufw --force enable
```

После `usermod` выйдите и войдите заново, иначе группа docker не подхватится.
Проверка: `docker info` отвечает без `sudo`.

**MTU.** На стенде за туннелем сборка зависала на `apt-get` из-за MTU 1450
(`.claude/rules/deploy.md`, «Сборка виснет на apt-get»). У DigitalOcean
обычно 1500, но проверить стоит секунду:

```bash
ip -o link show | grep -o 'eth0.*mtu [0-9]*'
```

Если не 1500, лечение там же в правиле.

## 2. Код: ключ к GitHub и клон

Репозиторий приватный, серверу нужен свой ключ. Не копируйте ключ со старой
машины: у каждой свой, старый потом отзывается.

**NEW:**

```bash
ssh-keygen -t ed25519 -C "lesson-tracker-prod-do" -N "" -f ~/.ssh/id_ed25519
cat ~/.ssh/id_ed25519.pub
```

Вывод добавьте на GitHub: репозиторий → Settings → Deploy keys → Add,
без права записи. Затем:

```bash
git clone git@github.com:leobreslav/lesson-tracker.git ~/lesson-tracker
cd ~/lesson-tracker
git checkout -B production origin/production
mkdir -p ~/backups/lesson-tracker
```

Дерево обязано стоять на `production`, иначе автовыкатка откажется работать.

## 3. Сертификаты со старого сервера

Выпустить новый сертификат на NEW нельзя, пока DNS смотрит на OLD: certbot
проверяет домен по HTTP. Поэтому сертификаты **переезжают**, а продление
потом заработает на NEW само, как только DNS переключён.

**Ноутбук:**

```bash
ssh leobreslav@OLD 'sudo tar czf - /etc/letsencrypt' > letsencrypt.tgz
scp letsencrypt.tgz leobreslav@NEW:
ssh leobreslav@NEW 'sudo tar xzf letsencrypt.tgz -C / && rm letsencrypt.tgz && sudo certbot certificates'
rm letsencrypt.tgz
```

`certbot certificates` на NEW должен показать `lbreslav.com` с датой
истечения. Хук перечитывания nginx ставится симлинком, а не копией:

**NEW:**

```bash
sudo ln -sf /home/leobreslav/lesson-tracker/scripts/reload-nginx.sh \
    /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
```

## 4. `.env.prod` и первый подъём

Файл едет с ноутбука тем же скриптом, что и всегда, только адрес контура
подменяется переменной: `scripts/contours.sh` до конца переезда трогать не
надо.

**Ноутбук:**

```bash
DEPLOY_SERVER=leobreslav@NEW ./scripts/sync-env.sh prod
```

Скрипт спросит про машину, кем она себя считает: чистый сервер отвечает
пустотой, это не отказ. Проверить, что файл на месте, значения не печатая:

```bash
ssh leobreslav@NEW 'cd lesson-tracker && grep -c = .env.prod && grep ^NGINX_SSL .env.prod'
```

`NGINX_SSL=true` в файле уже стоит, и сертификаты на NEW уже лежат, поэтому
стек поднимается сразу с TLS. Первый подъём делается руками, а не через
`deploy.sh`: тот тянет git и проверяет здоровье по `localhost`, а нам сперва
нужно просто собрать образы.

**NEW:**

```bash
cd ~/lesson-tracker
C="docker compose --env-file .env.prod -f docker-compose.prod.yml -f docker-compose.ssl.yml"
$C up -d --build
$C logs -f backend      # ждём Listening at: http://0.0.0.0:8000, Ctrl+C
$C ps -a                # frontend-build: Exited (0), остальные Up
curl -sk -o /dev/null -w '%{http_code}\n' https://localhost/    # 200
```

Сборка первый раз идёт несколько минут: `pip install` и `npm ci` без кэша.
База при этом **пустая**, это нормально: её мы сейчас заменим.

## 5. Репетиция переноса базы

Всё то же, что в день переезда, только OLD не останавливаем. Смысл: увидеть
NEW с настоящими данными и убедиться, что дамп ложится без ошибок.

Три грабли переноса описаны в `.claude/rules/deploy.md`, «Боевую базу на
стенд возят руками». Здесь роли одинаковые (`lessons`/`lessons`), но флаги
`--no-owner --no-acl` оставляем: они ничего не портят. Заливаем через снос
схемы, а не `--clean`, и обязательно погасив backend.

**Ноутбук:**

```bash
B=~/backups/migrate-$(date +%F)
mkdir -p $B
ssh leobreslav@OLD 'cd lesson-tracker && docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T db pg_dump -U lessons -d lessons --no-owner --no-acl' | gzip > $B/prod.sql.gz
ls -lh $B/prod.sql.gz
scp $B/prod.sql.gz leobreslav@NEW:
```

**NEW:**

```bash
cd ~/lesson-tracker
C="docker compose --env-file .env.prod -f docker-compose.prod.yml -f docker-compose.ssl.yml"
$C stop backend
$C exec -T db psql -U lessons -d lessons -v ON_ERROR_STOP=1 -c "
  DROP SCHEMA public CASCADE;
  CREATE SCHEMA public AUTHORIZATION lessons;
  GRANT ALL ON SCHEMA public TO public;"
zcat ~/prod.sql.gz | $C exec -T db psql -U lessons -d lessons -q -v ON_ERROR_STOP=1
$C start backend
$C logs --tail 30 backend      # migrate: No migrations to apply, bootstrap, gunicorn
```

Версия Postgres: оба контура на `postgres:16-alpine`, NEW скачал образ позже,
значит его psql не старше того, чем снимали. В эту сторону дамп с
`\restrict` в хвосте читается.

## 6. Проверка NEW по домену в обход DNS

Сертификат выписан на `lbreslav.com`, и проверять надо по этому имени.

**Ноутбук:**

```bash
curl -I --resolve lbreslav.com:443:NEW https://lbreslav.com/            # 200
curl -s --resolve lbreslav.com:443:NEW https://lbreslav.com/api/me/     # Authentication credentials were not provided
```

Чтобы посмотреть глазами и войти через Google, на время добавьте в
`/etc/hosts` ноутбука строку `NEW lbreslav.com www.lbreslav.com`, откройте
сайт, войдите, убедитесь, что видите свою школу, план, вложения (они
открываются: бакет тот же). Потом строку уберите.

Если что-то не так, чинится здесь, не спеша: OLD продолжает работать.

## 7. День переезда: окно записи

Всё ниже занимает минуты. Предупредите школу о коротком перерыве.

**OLD, остановить запись:**

```bash
cd ~/lesson-tracker
crontab -l > ~/crontab.backup     # на всякий случай
crontab -r                        # автовыкатка и бэкапы OLD больше не нужны
docker compose --env-file .env.prod -f docker-compose.prod.yml -f docker-compose.ssl.yml stop backend
```

С этого момента сайт на OLD отдаёт ошибку вместо API, и никто ничего не
допишет в старую базу. Crontab снят сознательно: иначе `backup-db.sh` со
старой машины продолжал бы каждую ночь класть **устаревшие** дампы в тот же
резервный бакет R2 под `db/`, а `prod-autodeploy.sh` выкатывал бы сервер,
которого уже нет в DNS.

**Ноутбук, свежий дамп:**

```bash
ssh leobreslav@OLD 'cd lesson-tracker && docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T db pg_dump -U lessons -d lessons --no-owner --no-acl' | gzip > $B/prod-final.sql.gz
scp $B/prod-final.sql.gz leobreslav@NEW:prod.sql.gz
```

`exec` в базу работает и при остановленном backend: контейнер `db` жив.

**NEW, залить:** повторить блок из шага 5 целиком, от `stop backend` до
`logs`. Он идемпотентен: сносит схему и заливает заново.

**Панель DNS:** A-записи `lbreslav.com` и `www.lbreslav.com` → NEW.

**Ноутбук, проверка:**

```bash
dig +short lbreslav.com            # NEW, обычно через 1–5 минут
curl -I https://lbreslav.com/      # 200, без --resolve
```

Откройте сайт в браузере, войдите, посмотрите на последние записи в
журнале: они должны быть теми, что были на OLD перед остановкой.

## 8. Дозаправить NEW: crontab и адрес контура

**NEW:**

```bash
crontab -e
```

```
*/5 * * * * /home/leobreslav/lesson-tracker/scripts/prod-autodeploy.sh
30 3 * * * /home/leobreslav/lesson-tracker/scripts/backup-db.sh >> /home/leobreslav/backups/backup.log 2>&1
0 4 * * * /home/leobreslav/lesson-tracker/scripts/backup-files.sh >> /home/leobreslav/backups/files.log 2>&1
```

Первый бэкап лучше не ждать до ночи, а дёрнуть руками и посмотреть лог:

```bash
~/lesson-tracker/scripts/backup-db.sh && tail -3 ~/backups/backup.log
```

Проверка продления сертификата на новом месте, теперь DNS уже смотрит сюда:

```bash
sudo certbot renew --dry-run
```

**Ноутбук, репозиторий.** Единственное место, где записан адрес прода,
это `scripts/contours.sh`. Одна правка:

```
SERVER="${DEPLOY_SERVER:-leobreslav@NEW}"
```

Старый IP упоминается ещё в прозе: `DEPLOY.md` (шапка и раздел 1),
`.claude/skills/deploy/SKILL.md` (перенос базы на стенд). Поправьте и их
тем же коммитом. Затем проверить, что все скрипты ходят куда надо:

```bash
./scripts/check-secrets.sh          # отпечатки прод и ноутбук совпадают
./push-deploy.sh --deploy-only      # обычная выкатка через новый адрес, ответ 200
```

`contour_matches_machine` теперь спросит NEW, кем тот себя считает, и получит
`lesson-tracker-prod` из имён контейнеров.

## 9. Старый сервер

Не выключайте его сразу. Неделю он лежит как страховка: база на нём
заморожена в момент переезда, и если на NEW что-то всплывёт, есть куда
посмотреть. Через неделю:

- удалить deploy key старого сервера на GitHub;
- `sudo tar czf` последний дамп `~/backups/lesson-tracker` к себе, если он
  там нужен (в R2 под `db/` они и так есть);
- снести сервер у хостера.

## Что может пойти не так

- **Сборка на NEW упала по памяти.** Признак: `npm run build` завершился
  сигналом или `Killed` в `docker compose logs frontend-build`. Своп из
  шага 1 поставлен? `free -h` покажет. Не помогло: временно поднять тариф в
  панели на время сборки.
- **`sync-env.sh` отказал: «называет себя не тем контуром».** Значит на NEW
  уже поднят стек с чужим именем проекта. Смотреть `docker ps` на NEW.
- **`psql` упал на `\restrict`.** Версия psql на NEW старше, чем pg_dump на
  OLD. Проверить `docker compose ... exec db psql --version` на обеих
  машинах; лечится `docker compose pull db` на NEW.
- **После переключения DNS браузер всё ещё показывает OLD.** Кэш DNS. `dig
  +short lbreslav.com` покажет, что видит сеть; браузеру помогает перезапуск.
  Пока TTL не истёк, часть людей будет попадать на OLD и видеть ошибку API,
  это и есть цена окна, и она ограничена TTL из шага 0.
- **Google-вход не работает на NEW при проверке через `/etc/hosts`.** Это
  нормально только если открыли сайт по IP, а не по имени: origin у клиента
  Google это `https://lbreslav.com`. По имени через `/etc/hosts` вход
  проходит.
