"""
Вход по коду из письма.

Третья дверь в приложение — после Google и дев-двери браузерных тестов, — и
единственная, которой может войти человек без Google-аккаунта. Заведена ради
родителей: импорт из ManageBac заводит их по адресу, который записала школа,
и у части из них Google-аккаунта на этом адресе нет.

Три правила, и все три про то, чего дверь **не** делает:

* **никого не заводит.** Код высылается только существующей учётке; иначе
  любой адрес входил бы в приложение. Учётки у нас появляются приглашением и
  импортом заранее, так что исключений нет;
* **не говорит, есть ли адрес.** Запрос кода отвечает одинаково для любого
  адреса — «если он нам известен, письмо ушло», — иначе форма входа стала бы
  справочником, кто в школе;
* **спрашивает список допущенных контура** (`door.py`), как обе другие
  двери, и до отправки письма: стенду с закрытым списком слать коды чужим
  незачем.

Почта здесь — не уведомление, а сама дверь. Поэтому письмо уходит **без**
`fail_silently`: не ушло — человеку сказано «не удалось отправить», а не
«проверьте почту». А без настроенной почты вне разработки дверь отказывает
кодом `email_login_unavailable`, вместо того чтобы печатать коды в лог,
который никто не читает.
"""

import hmac
import secrets
from datetime import timedelta
from hashlib import sha256

from config.errors import Codes, api_error, api_unavailable
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.utils import timezone
from rest_framework.authtoken.models import Token

from .door import NotAllowedHereError, refuse_unless_allowed
from .models import LoginCode

User = get_user_model()

# сколько кодов один адрес может запросить за время жизни кода: третий
# подряд — уже не «письмо не дошло», а заваливание чужой почты
REQUESTS_PER_LIFETIME = 3

CONSOLE_BACKEND = "django.core.mail.backends.console.EmailBackend"

# как приложение называет себя в письме; то же имя, что в шапке интерфейса
SITE_NAME = "Lesson Tracker"

# Письмо на языке учётки. Не через i18n: у бэкенда его нет, а две фразы на
# двух языках дешевле, чем заводить его ради них.
LETTERS = {
    "ru": (
        "Код для входа: {code}",
        "Здравствуйте!\n\nВаш код для входа в {site}: {code}\n\n"
        "Он действует {minutes} минут. Если вы не запрашивали код, просто "
        "не обращайте внимания на это письмо.\n",
    ),
    "en": (
        "Your sign-in code: {code}",
        "Hello!\n\nYour code to sign in to {site}: {code}\n\n"
        "It is valid for {minutes} minutes. If you did not ask for a code, "
        "simply ignore this message.\n",
    ),
}


def available() -> bool:
    """
    Можно ли вообще открыть эту дверь на этом контуре.

    Настроенная почта — да. В разработке — тоже: письма печатаются в лог
    контейнера, и код оттуда читается. Боевой контур без почты — нет: там
    лог не читает никто, и «проверьте почту» было бы ложью.
    """
    return settings.EMAIL_BACKEND != CONSOLE_BACKEND or settings.DEBUG


def digest(user, code: str) -> str:
    """Хэш кода, привязанный к учётке и к секрету установки."""
    message = f"{user.pk}:{code}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, sha256).hexdigest()


def find_user(email: str):
    address = (email or "").strip().lower()
    if not address:
        return None
    return User.objects.filter(email__iexact=address, is_active=True).first()


def request_code(email: str) -> bool:
    """
    Выслать код на адрес, если он наш. Возвращает, ушло ли письмо.

    Вызывающий ответ **не различает**: и незнакомый адрес, и адрес не из
    списка контура, и слишком частый запрос отвечают тем же «если адрес
    известен, письмо ушло». Отличается только отказ самой почты — он
    честный, потому что про существование адреса ничего не говорит.
    """
    if not available():
        api_unavailable(
            Codes.EMAIL_LOGIN_UNAVAILABLE,
            "Signing in by an emailed code is not set up on this server.",
        )

    user = find_user(email)
    if user is None:
        return False

    try:
        refuse_unless_allowed(user.email)
    except NotAllowedHereError:
        return False

    now = timezone.now()
    since = now - timedelta(minutes=LoginCode.LIFETIME_MINUTES)
    if user.login_codes.filter(created_at__gte=since).count() >= REQUESTS_PER_LIFETIME:
        return False

    code = f"{secrets.randbelow(10**6):06d}"
    # прежние открытые коды гаснут: действует всегда последний присланный,
    # иначе перебор шёл бы по нескольким сразу
    user.login_codes.filter(used_at__isnull=True).update(used_at=now)
    LoginCode.objects.create(
        user=user,
        code_hash=digest(user, code),
        expires_at=now + timedelta(minutes=LoginCode.LIFETIME_MINUTES),
    )

    subject, body = LETTERS.get(user.language, LETTERS["en"])
    context = {
        "code": code,
        "minutes": LoginCode.LIFETIME_MINUTES,
        "site": SITE_NAME,
    }
    try:
        sent = send_mail(
            subject.format(**context),
            body.format(**context),
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
    except Exception:
        sent = 0

    if not sent:
        api_unavailable(
            Codes.EMAIL_NOT_SENT,
            "The code could not be emailed. Try again in a minute.",
        )

    return True


def verify_code(email: str, code: str):
    """
    Проверить код и выдать токен. Или отказ с кодом, почему.

    Неверный код и незнакомый адрес — один и тот же отказ: различать их
    значило бы отвечать, есть ли адрес. Просроченный или исчерпанный код —
    другой отказ, потому что действие другое: не «попробуйте ещё раз», а
    «запросите новый».
    """
    user = find_user(email)
    row = (
        user.login_codes.filter(used_at__isnull=True).order_by("-created_at").first()
        if user is not None
        else None
    )
    if row is None:
        api_error(
            Codes.LOGIN_CODE_INVALID,
            "The code does not match this address.",
            field="code",
        )

    now = timezone.now()
    if row.expires_at <= now or row.attempts >= LoginCode.MAX_ATTEMPTS:
        row.used_at = now
        row.save(update_fields=["used_at"])
        api_error(
            Codes.LOGIN_CODE_EXPIRED,
            "The code has expired — request a new one.",
            field="code",
        )

    if not hmac.compare_digest(row.code_hash, digest(user, (code or "").strip())):
        row.attempts += 1
        row.save(update_fields=["attempts"])
        api_error(
            Codes.LOGIN_CODE_INVALID,
            "The code does not match this address.",
            field="code",
        )

    # список допущенных спрашивается и здесь: код мог быть выслан до того,
    # как список поменяли, а вход — это выдача токена, а не письмо. Отказ
    # тот же, что у Google-двери, и адрес в нём назван по той же причине
    try:
        refuse_unless_allowed(user.email)
    except NotAllowedHereError as exc:
        api_error(
            Codes.NOT_ALLOWED_HERE,
            "This installation does not admit this address.",
            email=exc.email,
        )

    row.used_at = now
    row.save(update_fields=["used_at"])
    user.last_login = now
    user.save(update_fields=["last_login"])

    token, _ = Token.objects.get_or_create(user=user)
    return token
