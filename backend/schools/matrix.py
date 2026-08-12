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

    # --- rule 1 and 2: an object owned by the school -------------------------

    def assertSchoolObjectRules(self, *, list_url, detail_url, obj, create, patch):
        """
        The whole matrix for one school-owned model.

        `create` is a body that must succeed for an administrator; `patch` a
        body that must change the existing object. Both are sent by several
        people, so they must not depend on who is signed in.
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

    # --- rule 3: an object owned by one teacher ------------------------------

    def assertPersonalObjectRules(self, *, list_url, detail_url, obj, patch):
        """
        The whole matrix for a model that belongs to one teacher.

        Nobody else reaches it — not a colleague sharing the course, not an
        administrator of the school, not another school. The role governs the
        school's shared objects, never somebody's work.
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
