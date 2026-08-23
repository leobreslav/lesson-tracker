"""
A way into the application for browser tests, and nothing else.

Signing in through Google cannot be driven from a headless browser, so the
e2e stack needs a door of its own. It is a door that must not exist anywhere
near production, so it is closed three times over:

* `E2E_TEST_LOGIN` is false unless the environment says otherwise, and the
  URLs are not even added to the routing table when it is off — a request to
  them gets an ordinary 404, with no hint that such a path was ever a thing;
* the views check the flag again at call time, so importing them by hand
  cannot help either;
* the reset endpoint runs `seed_demo`, which refuses to work with DEBUG off.

The production `.env.prod` never sets the flag, and `.env.prod.example` says
so out loud.

Четвёртый замок — для контура, где дверь открыта, но публика чужая.

Стенд держит флаг включённым нарочно: своих гугл-аккаунтов на четырнадцать
учеников не напасёшься, и «войти как» в меню ходит именно сюда. Пока стенд
был закрыт паролем nginx, этого хватало; пароля больше нет, а дверь,
выдающая токен **кому угодно по адресу**, без пароля равна открытому входу
учителем — и тремя замками выше она не закрывается ни одним: флаг включён,
маршруты есть, `seed_demo` про вход не спрашивают вовсе.

Поэтому: **есть список допущенных — дверь требует токен допущенного**
(`accounts/door.py`). Пустой список ничего не меняет, и это важно для
браузерных тестов: у их контура списка нет, они входят как входили.
"""

from config.errors import Codes, api_denied
from django.conf import settings
from django.core.management import call_command
from django.http import Http404
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .door import may_enter, open_to_everyone
from .models import User


def enabled() -> bool:
    return bool(getattr(settings, "E2E_TEST_LOGIN", False))


class E2EView(APIView):
    """Open to anyone — but only when the flag is on, and it never is."""

    # Токен читается, но не требуется: на контуре без списка допущенных дверь
    # открыта, и браузерные тесты входят ею, ещё не имея никакого токена.
    # Список нужен ровно затем, чтобы было **кого** спросить, когда он есть.
    authentication_classes = [TokenAuthentication]
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
            # переключатель перестал работать, — а не думать, что стенд слёг
            api_denied(
                Codes.NOT_ALLOWED_HERE,
                "This door answers only to the addresses this installation admits.",
            )

        return super().initial(request, *args, **kwargs)


class TestLoginView(E2EView):
    """
    A token for an existing account, by email.

    Deliberately does not create anybody: the tests run against `seed_demo`
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


class TestPeopleView(E2EView):
    """
    Кто есть в базе — чтобы можно было войти кем угодно в один клик.

    Своих гугл-аккаунтов на четырнадцать учеников не напасёшься, а
    плюс-адреса тут не работают вовсе: под алиасом в Google не войти, и
    id_token всё равно придёт с канонического адреса. Поэтому список людей
    отдаётся сюда, а переключатель в меню меняет токен в браузере — тем же
    путём, каким входят браузерные тесты.

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


class TestResetView(E2EView):
    """
    Put the database back to the seeded state.

    Each test starts from here, so one test cannot leave the next one a
    surprise. `seed_demo --flush` is the same command a developer runs by
    hand, which keeps the fixtures the tests see and the fixtures a person
    sees identical.
    """

    def post(self, request):
        call_command("seed_demo", flush=True, verbosity=0)
        return Response({"reset": True})
