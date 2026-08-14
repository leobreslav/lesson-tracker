"""
The access matrix as one call per model.

Every school object obeys the same four rules and every personal object the
same three. Written out per model that is forty near-identical assertions, and
the danger is not that one of them is wrong — it is that a model added later
never gets them at all.

So the rules live here as two assertions a test case makes about a model:

    self.assertSchoolObjectRules(
        list_url="course-list", detail_url="course-detail",
        obj=self.course, create={...}, patch={...},
    )

Read the helpers as the specification: if a rule ever changes, it changes in
one place and every model is re-checked at once.
"""

import re

from django.urls import reverse


class AccessRulesMixin:
    """
    Assertions about who may reach a model. Needs `SchoolTestMixin`'s cast.

    The two refusals are deliberately different and both are checked.

    Own school without the role: **403** with a code — the object is right
    there, it is simply not yours to change.

    Another school: the answer must not reveal that the object exists at all.
    For somebody carrying the admin role that means 404 from the queryset; a
    plain teacher of another school is stopped one step earlier, by the role
    check, and sees 403 — which says something about them, not about our
    object. So the assertion is indistinguishability from an id that never
    existed, and 404 specifically where the role would otherwise have let
    them through.
    """

    def assertAnswer(self, response, status, code=None):
        self.assertEqual(response.status_code, status, response.content)
        if code is not None:
            self.assertEqual(response.json().get("code"), code, response.content)

    # --- дополнительные действия вьюсета -------------------------------------

    def assertActionRules(self, *, actions, obj, people):
        """
        То же правило неотличимости, но для `@action`.

        Базовый класс вьюхи закрывает список и `detail`, а действие внутри
        ходит в модели своим кодом: `get_object_or_404` по queryset'у, а то и
        просто `objects.filter(pk=...)`. Сторож поверх роутеров такого не
        видит — класс на месте, права объявлены, — поэтому действия
        перечисляются здесь, рядом с моделью, которой они принадлежат.

        Проверяется ровно одно: ответ на **наш** id совпадает с ответом на
        id, которого никогда не было — и кодом, и телом. Что именно вернётся,
        зависит от действия и от того, кто спрашивает, и утверждением не
        является: у отфильтрованного списка это законные `200` и пустота, у
        действия по id — отказ. Важно, что по ответу нельзя узнать о
        существовании объекта, а тело сверяется потому, что как раз через
        него утечка и выглядела бы: пустой список против непустого при
        одинаковом коде.

        Действие описывается либо именем маршрута (id уезжает в путь), либо
        парой «имя, параметр» — тогда id уходит в query-строку, как у
        `/api/plan/?course=`.
        """
        missing = 10**9

        for spec in actions:
            name, param, method, body = self.normalize_action(spec)

            for person in people:
                with self.subTest(f"{name} ({method}) для {person.email}"):
                    self.sign_in(person)
                    call = getattr(self.client, method)

                    ours = call(
                        self.action_url(name, param, obj.pk), body, format="json"
                    )
                    unknown = call(
                        self.action_url(name, param, missing), body, format="json"
                    )

                    self.assertEqual(
                        (ours.status_code, self.without_id(ours, obj.pk)),
                        (unknown.status_code, self.without_id(unknown, missing)),
                        f"{name} выдаёт существование объекта: "
                        f"{ours.status_code} {ours.content} против "
                        f"{unknown.status_code} {unknown.content}",
                    )

    @staticmethod
    def without_id(response, pk):
        """
        Тело ответа без самого id.

        Отказ DRF повторяет присланное значение («Invalid pk "10"»), и
        сравнивать такие тела дословно нельзя: они различаются тем, что мы
        сами и прислали. Всё остальное в теле сравнивается как есть —
        пустой список против непустого при одинаковом коде это и есть та
        утечка, которую ищем.
        """
        return re.sub(rf"\b{pk}\b", "<id>", response.content.decode())

    @staticmethod
    def normalize_action(spec):
        """`"name"` | `("name", "param")` | `{...}` — к одному виду."""
        if isinstance(spec, str):
            spec = {"name": spec}
        elif isinstance(spec, tuple):
            spec = dict(zip(("name", "param"), spec))

        return (
            spec["name"],
            spec.get("param"),
            spec.get("method", "get"),
            spec.get("body", {}),
        )

    @staticmethod
    def action_url(name, param, pk):
        if param is None:
            return reverse(name, args=[pk])
        return f"{reverse(name)}?{param}={pk}"

    # --- rule 1 and 2: an object owned by the school -------------------------

    def assertSchoolObjectRules(
        self, *, list_url, detail_url, obj, create, patch, actions=()
    ):
        """
        The whole matrix for one school-owned model.

        `create` is a body that must succeed for an administrator; `patch` a
        body that must change the existing object. Both are sent by several
        people, so they must not depend on who is signed in.

        `actions` — дополнительные действия вьюсета: их закрывает не базовый
        класс, а собственный код внутри, и проверяются они тем же правилом
        неотличимости.
        """
        detail = reverse(detail_url, args=[obj.pk])
        listing = reverse(list_url)

        with self.subTest(f"{list_url}: свой учитель читает"):
            self.sign_in(self.user)
            response = self.client.get(listing)
            self.assertEqual(response.status_code, 200, response.content)
            self.assertIn(obj.pk, [item["id"] for item in response.json()])

        with self.subTest(f"{list_url}: свой учитель не пишет"):
            self.sign_in(self.user)
            self.assertAnswer(
                self.client.post(listing, create, format="json"),
                403,
                "school_admin_required",
            )
            self.assertAnswer(
                self.client.patch(detail, patch, format="json"),
                403,
                "school_admin_required",
            )
            self.assertAnswer(
                self.client.delete(detail), 403, "school_admin_required"
            )

        with self.subTest(f"{list_url}: свой администратор пишет"):
            self.sign_in(self.admin)
            self.assertEqual(
                self.client.post(listing, create, format="json").status_code,
                201,
            )
            self.assertEqual(
                self.client.patch(detail, patch, format="json").status_code, 200
            )

        with self.subTest(f"{list_url}: чужая школа не видит объекта"):
            # the property that matters is not a particular number but
            # indistinguishability: a stranger must get the same answer for
            # our object as for an id that never existed, or the status code
            # itself would confirm the object is there
            missing = reverse(detail_url, args=[10**9])

            for person in (self.stranger, self.alien_admin):
                self.sign_in(person)

                for method, args in (
                    ("get", ()),
                    ("patch", (patch,)),
                    ("delete", ()),
                ):
                    call = getattr(self.client, method)
                    ours = call(detail, *args, format="json").status_code
                    unknown = call(missing, *args, format="json").status_code

                    self.assertEqual(
                        ours,
                        unknown,
                        f"{method} выдаёт существование объекта: {ours} против {unknown}",
                    )
                    self.assertIn(ours, (403, 404))

                self.assertNotIn(
                    obj.pk, [item["id"] for item in self.client.get(listing).json()]
                )

        with self.subTest(f"{list_url}: чужой администратор получает 404, не 403"):
            # a role they do have, an object they may not know about: the
            # refusal has to come from the queryset, not from the permission
            self.sign_in(self.alien_admin)
            self.assertEqual(self.client.get(detail).status_code, 404)
            self.assertEqual(
                self.client.patch(detail, patch, format="json").status_code, 404
            )

        with self.subTest(f"{list_url}: без школы — no_school"):
            self.sign_in(self.outsider)
            self.assertAnswer(self.client.get(listing), 403, "no_school")
            self.assertAnswer(
                self.client.post(listing, create, format="json"), 403, "no_school"
            )

        self.assertActionRules(
            actions=actions, obj=obj, people=(self.stranger, self.alien_admin)
        )

    # --- rule 3: an object owned by one teacher ------------------------------

    def assertPersonalObjectRules(
        self, *, list_url, detail_url, obj, patch, actions=()
    ):
        """
        The whole matrix for a model that belongs to one teacher.

        Nobody else reaches it — not a colleague sharing the course, not an
        administrator of the school, not another school. The role governs the
        school's shared objects, never somebody's work.

        `actions` проверяются строже, чем у школьного объекта: коллега и
        администратор своей школы тоже не должны отличать чужой урок от
        несуществующего.
        """
        detail = reverse(detail_url, args=[obj.pk])
        listing = reverse(list_url)
        model = type(obj)

        with self.subTest(f"{list_url}: владелец видит своё"):
            self.sign_in(self.user)
            self.assertEqual(self.client.get(detail).status_code, 200)

        with self.subTest(f"{list_url}: чужие не видят и не правят"):
            for person in (self.colleague, self.admin, self.stranger):
                self.sign_in(person)
                self.assertEqual(self.client.get(detail).status_code, 404)
                self.assertEqual(
                    self.client.patch(detail, patch, format="json").status_code, 404
                )
                self.assertEqual(self.client.delete(detail).status_code, 404)
                self.assertNotIn(
                    obj.pk, [item["id"] for item in self.client.get(listing).json()]
                )

        # nothing above may have gone through
        self.assertTrue(model.objects.filter(pk=obj.pk).exists())

        with self.subTest(f"{list_url}: без школы — no_school"):
            self.sign_in(self.outsider)
            self.assertAnswer(self.client.get(listing), 403, "no_school")
