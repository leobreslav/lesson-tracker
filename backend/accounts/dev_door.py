"""
A way into the application for development, and nothing else.

Signing in through Google needs a real Google account per person, and a
seeded school has fourteen students and a staff room of teachers. So local
development and cloud sessions have a door of their own: «Войти как» in the
user menu asks it for a token by email. It is a door that must not exist
anywhere near production, so it is closed twice over:

* `DEV_LOGIN` is false unless the environment says otherwise, and the URLs
  are not even added to the routing table when it is off — a request to
  them gets an ordinary 404, with no hint that such a path was ever a thing;
* the views check the flag again at call time, so importing them by hand
  cannot help either.

The production `.env.prod` never sets the flag, and `.env.prod.example` says
so out loud.

Третий замок — для контура, где дверь открыта, но публика чужая.

Дверь выдаёт токен **кому угодно по адресу**, без Google и без пароля. На
своей машине это ровно то, что нужно; на машине, открытой наружу, это
открытый вход учителем — и двумя замками выше она не закрывается ни одним:
флаг включён, маршруты есть. Так было на упразднённом стенде, пока его не
закрыли списком.

Поэтому: **есть список допущенных — дверь требует токен допущенного**
(`accounts/door.py`). Пустой список ничего не меняет, и так живёт машина
разработчика: она наружу не смотрит. Выкатить пару «дверь включена, список
пуст» не даёт `scripts/check-login-door.sh`.
"""

from config.errors import Codes, api_denied
from django.conf import settings
from django.http import Http404
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .door import may_enter, open_to_everyone
from .models import User


def enabled() -> bool:
    return bool(getattr(settings, "DEV_LOGIN", False))


class TokenIfItIsAnyGood(TokenAuthentication):
    """
    Токен, если он есть и годен; иначе аноним, а не отказ.

    Штатная `TokenAuthentication` на неизвестном токене отвечает 401 и до
    вьюхи не пускает вовсе. Для этой двери это была бы поломка на ровном
    месте: после пересева базы в браузере остаётся токен от снесённой базы,
    и дверь, которой токен не нужен вообще (списка допущенных нет), ответила
    бы отказом — а выглядело бы это как «переключатель аккаунтов пропал».

    На контуре со списком ничего не теряется: без токена запрос всё равно
    получает 403 с нашим кодом, то есть тот отказ, который тут и надо
    показать, — а не 401 от чужого механизма.
    """

    def authenticate(self, request):
        try:
            return super().authenticate(request)
        except AuthenticationFailed:
            return None


class DevDoorView(APIView):
    """Open to anyone — but only when the flag is on, and it never is in production."""

    # Токен читается, но не требуется: на машине без списка допущенных дверь
    # открыта, и в неё входят, ещё не имея никакого токена. Список нужен
    # ровно затем, чтобы было **кого** спросить, когда он есть.
    authentication_classes = [TokenIfItIsAnyGood]
    permission_classes = [AllowAny]

    def initial(self, request, *args, **kwargs):
        if not enabled():
            # 404 rather than 403: a closed door should look like no door
            raise Http404

        if not open_to_everyone() and not may_enter(
            getattr(request.user, "email", None)
        ):
            # 403 с кодом, а не 404: дверь тут есть, и человек, у которого
            # токен уже подменён на ученический, должен понимать, почему
            # переключатель перестал работать, — а не думать, что сайт слёг
            api_denied(
                Codes.NOT_ALLOWED_HERE,
                "This door answers only to the addresses this installation admits.",
            )

        return super().initial(request, *args, **kwargs)


class DevLoginView(DevDoorView):
    """
    A token for an existing account, by email.

    Deliberately does not create anybody: the door works against `seed_demo`
    data, and an endpoint that could invent users would be a second way to
    get into a school.
    """

    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        user = User.objects.filter(email__iexact=email).first()

        if user is None:
            return Response({"detail": f"no such user: {email}"}, status=404)

        token, _ = Token.objects.get_or_create(user=user)
        return Response(
            {
                "key": token.key,
                "email": user.email,
                "school": user.school_id,
                "is_school_admin": user.is_school_admin,
            }
        )


class DevPeopleView(DevDoorView):
    """
    Кто есть в базе — чтобы можно было войти кем угодно в один клик.

    Своих гугл-аккаунтов на четырнадцать учеников не напасёшься, а
    плюс-адреса тут не работают вовсе: под алиасом в Google не войти, и
    id_token всё равно придёт с канонического адреса. Поэтому список людей
    отдаётся сюда, а переключатель в меню меняет токен в браузере.

    Живёт за тем же флагом, что и вход: без него маршрут не существует.
    """

    def get(self, request):
        # сотрудники первыми: переключаются чаще к ним, а класс целиком —
        # это тринадцать строк, за которыми учителя было бы не видно
        people = User.objects.select_related("school").order_by(
            "-kind", "first_name", "last_name", "email"
        )

        return Response(
            {
                "people": [
                    {
                        "email": person.email,
                        "name": " ".join(
                            filter(None, (person.first_name, person.last_name))
                        )
                        or person.email,
                        "kind": person.kind,
                        "school": person.school.name if person.school else None,
                        "is_school_admin": person.is_school_admin,
                        "is_superuser": person.is_superuser,
                    }
                    for person in people
                ]
            }
        )
