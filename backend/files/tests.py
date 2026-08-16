"""
Files, and the one property the whole design exists for: sharing.

The interesting assertions here are not about HTTP codes but about what is
left in the store afterwards. A file has to survive one teacher deleting it
and disappear when the last one does, and the only honest way to check that
is to ask the store — which is why the fixtures upload for real (into an
in-memory backend) instead of inventing rows.

Deletion is deferred to transaction commit on purpose (see `signals`), so
every test that expects an object to vanish wraps the call in
`captureOnCommitCallbacks`. Forgetting it makes a test fail rather than pass
by accident, which is the right way round.
"""

import logging
from contextlib import contextmanager
from datetime import date, timedelta
from io import BytesIO, StringIO
from unittest import mock

from botocore.exceptions import EndpointConnectionError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from django.urls import reverse
from library.models import PlanTemplateRow
from library.services import import_into_course
from plans.models import PlanNode
from rest_framework.test import APITestCase
from schools.testing import (
    assign,
    SchoolTestMixin,
    make_attachment,
    make_course,
    make_node,
    make_stored_file,
    make_subject,
    make_template,
    make_upload,
)

from . import services, storage
from .management.commands import backup_db
from .models import Attachment, StoredFile

# a lesson body worth round-tripping: two kinds of maths, a blank line and a
# backslash command, all of which a careless «clean up the text» step eats
MARKDOWN = (
    "## Теорема Пифагора\n"
    "\n"
    "Для прямоугольного треугольника $a^2 + b^2 = c^2$.\n"
    "\n"
    "$$\\int_0^1 x^2\\,dx = \\frac{1}{3}$$\n"
    "\n"
    "* пункт со звёздочкой\\*\n"
    "* второй   пункт с   пробелами\n"
)


class BrokenStore:
    """A storage backend that is having a bad day. No `bucket`, no luck."""

    failure = EndpointConnectionError(endpoint_url="https://r2.example")

    def save(self, *args, **kwargs):
        raise self.failure

    def delete(self, *args, **kwargs):
        raise self.failure

    def exists(self, *args, **kwargs):
        raise self.failure

    def url(self, *args, **kwargs):
        raise self.failure

    def listdir(self, *args, **kwargs):
        raise self.failure


@contextmanager
def broken_storage():
    """R2 is down for the length of the block. The warnings it logs are the
    point of the test, so there is no need to shout them at whoever is
    reading the run."""
    logging.disable(logging.WARNING)
    try:
        with mock.patch.object(storage, "backend", return_value=BrokenStore()):
            yield
    finally:
        logging.disable(logging.NOTSET)


class FilesTestCase(SchoolTestMixin, APITestCase):
    """One course, one lesson in it, and a file to hang off that lesson."""

    def setUp(self):
        super().setUp()
        self.course = make_course(self.school, name="9Б Алгебра")
        assign(self.user, self.course)
        self.lesson = make_node(self.user, self.course, "Теорема Пифагора")

    # --- helpers -------------------------------------------------------------

    def attach_via_api(self, row="lesson", **kwargs):
        target = self.lesson if row == "lesson" else row
        field = "template_row" if hasattr(target, "is_header") else "plan_row"

        payload = {field: target.pk, "file": make_upload(**kwargs)}
        return self.client.post(reverse("attachment-list"), payload, format="multipart")

    def stored_keys(self):
        return sorted(StoredFile.objects.values_list("key", flat=True))

    def in_store(self, key) -> bool:
        return storage.exists(key)


# --- lesson content ------------------------------------------------------------


class LessonContentTests(FilesTestCase):
    def test_markdown_survives_a_round_trip_untouched(self):
        url = reverse("plannode-detail", args=[self.lesson.pk])

        saved = self.client.patch(
            url,
            {"body": MARKDOWN, "objectives": "A: knowing and understanding"},
            format="json",
        )
        self.assertEqual(saved.status_code, 200)

        read = self.client.get(url)
        # byte for byte: the LaTeX, the blank lines, the double spaces
        self.assertEqual(read.data["body"], MARKDOWN)
        self.assertEqual(self.lesson.__class__.objects.get(pk=self.lesson.pk).body, MARKDOWN)

    def test_the_tree_carries_a_flag_and_not_the_text(self):
        self.lesson.body = MARKDOWN
        self.lesson.save(update_fields=["body"])

        tree = self.client.get(f"/api/plan/?course={self.course.pk}")
        node = tree.data["nodes"][0]

        self.assertTrue(node["has_content"])
        self.assertNotIn("body", node)

    def test_a_section_header_refuses_content(self):
        section = make_node(self.user, self.course, "Тема", section=True)

        refused = self.client.patch(
            reverse("plannode-detail", args=[section.pk]),
            {"body": "нельзя"},
            format="json",
        )

        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.data["code"], "content_on_section")


# --- uploading -----------------------------------------------------------------


class UploadTests(FilesTestCase):
    def test_a_file_is_stored_and_referenced(self):
        response = self.attach_via_api()
        self.assertEqual(response.status_code, 201)

        stored = StoredFile.objects.get()
        self.assertEqual(stored.school, self.school)
        self.assertEqual(stored.uploaded_by, self.user)
        self.assertTrue(stored.key.startswith(f"files/{self.school.pk}/"))
        self.assertTrue(self.in_store(stored.key))
        self.assertFalse(response.data["is_shared"])

    def test_the_same_bytes_are_uploaded_once(self):
        first = self.attach_via_api()
        second_lesson = make_node(self.user, self.course, "Второй урок", position=1)
        second = self.attach_via_api(row=second_lesson)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)

        # two references, one object — and both now say so
        self.assertEqual(StoredFile.objects.count(), 1)
        self.assertEqual(Attachment.objects.count(), 2)
        self.assertTrue(second.data["is_shared"])

    def test_a_different_file_of_the_same_size_is_not_confused_for_it(self):
        self.attach_via_api(content=b"%PDF-1.4 aaaa")
        other = make_node(self.user, self.course, "Второй урок", position=1)
        self.attach_via_api(row=other, content=b"%PDF-1.4 bbbb")

        self.assertEqual(StoredFile.objects.count(), 2)

    def test_a_file_larger_than_the_limit_is_refused(self):
        with self.settings(FILE_MAX_BYTES=100):
            refused = self.attach_via_api(content=b"x" * 200)

        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.data["code"], "file_too_large")
        self.assertFalse(StoredFile.objects.exists())

    def test_the_school_quota_stops_the_next_upload(self):
        with self.settings(SCHOOL_FILE_QUOTA_BYTES=10):
            refused = self.attach_via_api(content=b"x" * 50)

        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.data["code"], "school_quota_exceeded")

    def test_the_quota_counts_a_shared_file_once(self):
        stored = make_stored_file(self.school, self.user, content=b"x" * 40)
        make_attachment(self.lesson, stored)
        second = make_node(self.user, self.course, "Второй", position=1)
        make_attachment(second, stored)

        self.assertEqual(services.quota_used(self.school.pk), stored.size)

    def test_an_executable_is_refused_by_its_extension(self):
        refused = self.attach_via_api(
            name="lesson.exe", kind="application/octet-stream"
        )

        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.data["code"], "file_type_not_allowed")

    def test_a_pdf_named_as_an_image_is_refused_by_its_type(self):
        refused = self.attach_via_api(name="picture.png", kind="application/pdf")

        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.data["code"], "file_type_not_allowed")

    def test_a_browser_that_does_not_know_the_type_is_still_believed(self):
        allowed = self.attach_via_api(
            name="plan.docx", kind="application/octet-stream"
        )
        self.assertEqual(allowed.status_code, 201)

    def test_a_link_needs_no_file(self):
        response = self.client.post(
            reverse("attachment-list"),
            {
                "plan_row": self.lesson.pk,
                "url": "https://example.org/task",
                "title": "Задачи",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["kind"], "link")
        self.assertFalse(StoredFile.objects.exists())

    def test_a_section_header_takes_no_attachments(self):
        section = make_node(self.user, self.course, "Тема", section=True)
        refused = self.attach_via_api(row=section)

        self.assertEqual(refused.status_code, 400)


# --- what happens when references go -------------------------------------------


class LifecycleTests(FilesTestCase):
    def setUp(self):
        super().setUp()
        self.other_lesson = make_node(self.user, self.course, "Второй урок", position=1)
        self.stored = make_stored_file(self.school, self.user)
        self.mine = make_attachment(self.lesson, self.stored)
        self.theirs = make_attachment(self.other_lesson, self.stored)

    def test_dropping_one_reference_leaves_the_file_alone(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.delete(
                reverse("attachment-detail", args=[self.mine.pk])
            )

        self.assertEqual(response.status_code, 204)
        self.assertTrue(StoredFile.objects.filter(pk=self.stored.pk).exists())
        self.assertTrue(self.in_store(self.stored.key))

    def test_dropping_the_last_reference_removes_the_object(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.delete(reverse("attachment-detail", args=[self.mine.pk]))
            self.client.delete(reverse("attachment-detail", args=[self.theirs.pk]))

        self.assertFalse(StoredFile.objects.exists())
        self.assertFalse(self.in_store(self.stored.key))

    def test_deleting_a_lesson_does_not_break_the_other_one(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.delete(
                reverse("plannode-detail", args=[self.lesson.pk])
            )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Attachment.objects.filter(pk=self.mine.pk).exists())
        # the colleague's reference and the file behind it are untouched
        self.assertTrue(Attachment.objects.filter(pk=self.theirs.pk).exists())
        self.assertTrue(self.in_store(self.stored.key))

    def test_the_files_outlive_the_teacher_who_uploaded_them(self):
        """
        План принадлежит курсу, и вложения вместе с ним.

        Раньше уход человека уносил его план каскадом, а с планом — файлы.
        Теперь программа курса переживает смену ведущего целиком: следующий
        открывает её со всеми материалами.
        """
        with self.captureOnCommitCallbacks(execute=True):
            self.user.delete()

        self.assertTrue(Attachment.objects.filter(pk=self.mine.pk).exists())
        self.assertTrue(StoredFile.objects.filter(pk=self.stored.pk).exists())
        self.assertTrue(self.in_store(self.stored.key))

    def test_a_course_with_a_plan_still_refuses_to_be_deleted(self):
        """PROTECT on the plan already guards this; files must not weaken it."""
        with self.assertRaises(Exception):
            self.course.delete()

    def test_deleting_a_template_leaves_the_plans_that_took_it(self):
        template = make_template(
            self.school, self.user, subject=make_subject(self.school),
            rows=((False, "Урок из шаблона"),),
        )
        row = template.rows.get()
        make_attachment(row, self.stored)

        with self.captureOnCommitCallbacks(execute=True):
            template.delete()

        self.assertTrue(self.in_store(self.stored.key))
        self.assertEqual(Attachment.objects.filter(stored_file=self.stored).count(), 2)

    def test_a_school_holding_files_is_refused_and_told_what_holds_it(self):
        """
        The cascade nobody asked about, which is why it is worth a test.

        Files hold a school through `StoredFile.school`, and the refusal used
        to say «still has N members» whatever the real reason was. That is a
        message that sends somebody looking for people when the blocker is a
        worksheet, so it now names what the database actually named.
        """
        self.sign_in(self.make_root("root@example.com", school=None))

        response = self.client.delete(
            reverse("school-detail", args=[self.school.pk])
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "school_in_use")

        blocked = response.data["params"]["blocked_by"]
        self.assertIn("attachments", blocked)
        self.assertIn("users", blocked)
        # and nothing was taken out of the bucket on the way to refusing
        self.assertTrue(self.in_store(self.stored.key))

    def test_a_storage_refusal_keeps_the_row_for_the_cleanup_command(self):
        Attachment.objects.filter(pk=self.theirs.pk).delete()

        with broken_storage(), self.captureOnCommitCallbacks(execute=True):
            Attachment.objects.filter(pk=self.mine.pk).delete()

        # nothing points at it any more, but the row survives: a row without
        # references is a to-do item, a missing row is rubbish nobody can name
        self.assertTrue(StoredFile.objects.filter(pk=self.stored.pk).exists())
        self.assertTrue(self.in_store(self.stored.key))


# --- sharing through the library -----------------------------------------------


class SharedThroughLibraryTests(FilesTestCase):
    def setUp(self):
        super().setUp()
        self.stored = make_stored_file(self.school, self.user)
        make_attachment(self.lesson, self.stored, title="Карточка")
        self.lesson.body = MARKDOWN
        self.lesson.save(update_fields=["body"])

        self.template = self.publish()

    def publish(self):
        response = self.client.post(
            "/api/library/templates/from-plan/",
            {
                "course": self.course.pk,
                "title": "Алгебра 9",
                "subject": make_subject(self.school).pk,
                "grade": 9,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

        from library.models import PlanTemplate

        template = PlanTemplate.objects.get(pk=response.data["id"])
        template.is_published = True
        template.save(update_fields=["is_published"])
        return template

    def test_publishing_a_plan_points_the_template_at_the_same_file(self):
        row = self.template.rows.get()

        self.assertEqual(row.body, MARKDOWN)
        self.assertEqual(row.attachments.get().stored_file_id, self.stored.pk)
        self.assertEqual(StoredFile.objects.count(), 1)

    def test_taking_a_template_copies_no_bytes(self):
        colleague_course = make_course(self.school, self.course.year, name="9В Алгебра")

        result = import_into_course(
            template=self.template, course_id=colleague_course.pk, append=False
        )

        self.assertEqual(result["created_attachments"], 1)
        # one object in the bucket, three references to it: mine, the shelf's
        # and the colleague's
        self.assertEqual(StoredFile.objects.count(), 1)
        self.assertEqual(self.stored.attachments.count(), 3)

        theirs = PlanNode.objects.get(course=colleague_course)
        self.assertEqual(theirs.body, MARKDOWN)
        self.assertEqual(theirs.attachments.get().stored_file_id, self.stored.pk)

    def test_the_colleague_who_took_it_can_download_the_file(self):
        colleague_course = make_course(self.school, self.course.year, name="9В Алгебра")
        assign(self.colleague, colleague_course)
        import_into_course(
            template=self.template, course_id=colleague_course.pk, append=False
        )

        theirs = PlanNode.objects.get(course=colleague_course).attachments.get()
        self.sign_in(self.colleague)

        answer = self.client.get(
            reverse("attachment-download", args=[theirs.pk]) + "?json=1"
        )
        self.assertEqual(answer.status_code, 200)
        self.assertIn("url", answer.data)

    def test_the_colleague_deleting_their_copy_leaves_mine(self):
        colleague_course = make_course(self.school, self.course.year, name="9В Алгебра")
        assign(self.colleague, colleague_course)
        import_into_course(
            template=self.template, course_id=colleague_course.pk, append=False
        )
        theirs = PlanNode.objects.get(course=colleague_course).attachments.get()

        self.sign_in(self.colleague)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.delete(reverse("attachment-detail", args=[theirs.pk]))

        self.assertTrue(self.in_store(self.stored.key))
        self.assertEqual(self.stored.attachments.count(), 2)

    def test_refreshing_the_template_keeps_its_files(self):
        self.client.post(
            f"/api/library/templates/{self.template.pk}/update-from-plan/",
            {"course": self.course.pk},
            format="json",
        )

        self.assertEqual(StoredFile.objects.count(), 1)
        self.assertTrue(self.in_store(self.stored.key))
        self.assertEqual(self.template.rows.get().attachments.count(), 1)

    def test_rewriting_the_rows_keeps_the_files_of_named_rows(self):
        row = self.template.rows.get()

        response = self.client.put(
            f"/api/library/templates/{self.template.pk}/rows/",
            [{"id": row.pk, "is_header": False, "title": "Переименован"}],
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(PlanTemplateRow.objects.get().attachments.count(), 1)
        self.assertTrue(self.in_store(self.stored.key))


# --- who may reach what ---------------------------------------------------------


class AttachmentAccessTests(FilesTestCase):
    def setUp(self):
        super().setUp()
        self.stored = make_stored_file(self.school, self.user)
        self.mine = make_attachment(self.lesson, self.stored)

        # a colleague's lesson in the same school, with its own file
        their_course = make_course(self.school, self.course.year, name="9В Алгебра")
        their_lesson = make_node(self.colleague, their_course, "Их урок")
        self.theirs = make_attachment(
            their_lesson, make_stored_file(self.school, self.colleague, content=b"other")
        )

        # and one in another school entirely
        alien_course = make_course(self.alien_school, name="9А")
        alien_lesson = make_node(self.stranger, alien_course, "Чужой урок")
        self.alien = make_attachment(
            alien_lesson,
            make_stored_file(self.alien_school, self.stranger, content=b"alien"),
        )

    def download(self, attachment):
        return self.client.get(reverse("attachment-download", args=[attachment.pk]))

    def test_my_own_attachment_downloads(self):
        self.assertEqual(self.download(self.mine).status_code, 302)

    def test_a_colleagues_lesson_says_not_yours(self):
        answer = self.download(self.theirs)

        self.assertEqual(answer.status_code, 403)
        self.assertEqual(answer.data["code"], "attachment_forbidden")

    def test_another_schools_file_does_not_exist(self):
        """The stronger claim: the same answer as an id that never was."""
        real = self.download(self.alien)
        invented = self.client.get(reverse("attachment-download", args=[10**9]))

        self.assertEqual(real.status_code, 404)
        self.assertEqual(real.status_code, invented.status_code)

    def test_the_list_shows_only_my_own(self):
        listed = self.client.get(reverse("attachment-list"))
        ids = {item["id"] for item in listed.data}

        self.assertEqual(ids, {self.mine.pk})

    def test_a_published_template_is_readable_by_the_school(self):
        template = make_template(
            self.school, self.colleague, rows=((False, "Урок"),), published=True
        )
        row = template.rows.get()
        shared = make_attachment(row, self.stored)

        self.assertEqual(self.download(shared).status_code, 302)
        # readable, but not mine to remove
        removed = self.client.delete(reverse("attachment-detail", args=[shared.pk]))
        self.assertEqual(removed.status_code, 403)

    def test_a_colleagues_draft_is_out_of_reach(self):
        draft = make_template(
            self.school, self.colleague, rows=((False, "Урок"),), published=False
        )
        hidden = make_attachment(draft.rows.get(), self.stored)

        self.assertEqual(self.download(hidden).status_code, 403)

    def test_a_person_with_no_school_is_told_so(self):
        self.sign_in(self.outsider)
        answer = self.download(self.mine)

        self.assertEqual(answer.status_code, 403)
        self.assertEqual(answer.data["code"], "no_school")

    def test_an_upload_cannot_name_a_lesson_of_another_course(self):
        theirs = make_course(self.school, self.course.year, name="9Г Алгебра")
        their_lesson = make_node(self.colleague, theirs, "Их урок")

        refused = self.client.post(
            reverse("attachment-list"),
            {"plan_row": their_lesson.pk, "file": make_upload()},
            format="multipart",
        )

        self.assertEqual(refused.status_code, 400)


# --- the store having a bad day --------------------------------------------------


class StorageOutageTests(FilesTestCase):
    def test_the_plan_still_loads(self):
        make_attachment(self.lesson, make_stored_file(self.school, self.user))

        with broken_storage():
            tree = self.client.get(f"/api/plan/?course={self.course.pk}")
            detail = self.client.get(reverse("plannode-detail", args=[self.lesson.pk]))
            listed = self.client.get(
                reverse("attachment-list") + f"?plan_row={self.lesson.pk}"
            )

        # nothing here needs the store, so nothing here may fail because of it
        self.assertEqual(tree.status_code, 200)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.data), 1)

    def test_an_upload_says_try_again_later(self):
        with broken_storage():
            refused = self.attach_via_api()

        self.assertEqual(refused.status_code, 503)
        self.assertEqual(refused.data["code"], "storage_unavailable")
        # and nothing was recorded for an object that never arrived
        self.assertFalse(StoredFile.objects.exists())

    def test_a_download_says_try_again_later(self):
        attachment = make_attachment(
            self.lesson, make_stored_file(self.school, self.user)
        )

        with broken_storage():
            answer = self.client.get(
                reverse("attachment-download", args=[attachment.pk])
            )

        self.assertEqual(answer.status_code, 503)


# --- housekeeping ------------------------------------------------------------------


class CleanupCommandTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.course = make_course(self.school, name="9Б Алгебра")
        self.lesson = make_node(self.user, self.course, "Урок")

    def run_cleanup(self, delete=False, quiet=False):
        out = StringIO()
        call_command(
            "cleanup_orphaned_files",
            delete=delete,
            quiet=quiet,
            stdout=out,
            stderr=out,
        )
        return out.getvalue()

    def test_quiet_says_nothing_when_there_is_nothing(self):
        """
        Так эта команда и стоит в cron: пустой лог — это «всё в порядке».

        Еженедельная строка «сирот нет» через год стала бы всем логом, и
        настоящую находку в нём никто бы не заметил.
        """
        self.assertEqual(self.run_cleanup(quiet=True).strip(), "")

    def test_quiet_still_reports_a_find(self):
        stored = make_stored_file(self.school, self.user)

        self.assertIn(stored.key, self.run_cleanup(quiet=True))

    def test_it_only_reports_until_told_otherwise(self):
        stored = make_stored_file(self.school, self.user)

        output = self.run_cleanup()

        self.assertIn(stored.key, output)
        self.assertIn("--delete", output)
        self.assertTrue(StoredFile.objects.exists())
        self.assertTrue(storage.exists(stored.key))

    def test_it_removes_a_record_nothing_points_at(self):
        stored = make_stored_file(self.school, self.user)

        self.run_cleanup(delete=True)

        self.assertFalse(StoredFile.objects.exists())
        self.assertFalse(storage.exists(stored.key))

    def test_it_removes_an_object_no_record_knows_about(self):
        orphan = storage.save(
            storage.build_key(self.school.pk, "stray.pdf"), make_upload()
        )

        self.run_cleanup(delete=True)

        self.assertFalse(storage.exists(orphan))

    def test_it_leaves_a_file_somebody_uses(self):
        stored = make_stored_file(self.school, self.user)
        make_attachment(self.lesson, stored)

        self.run_cleanup(delete=True)

        self.assertTrue(StoredFile.objects.filter(pk=stored.pk).exists())
        self.assertTrue(storage.exists(stored.key))

    def test_a_dead_store_does_not_stop_the_database_half(self):
        make_stored_file(self.school, self.user)

        with broken_storage():
            output = self.run_cleanup()

        self.assertIn("хранилище не отвечает", output)
        self.assertIn("записи без единого вложения: 1", output)


# --- the backup bucket ----------------------------------------------------------------


class FakeR2:
    """
    Two buckets and the three calls the backup command makes.

    A fake rather than moto because what is being tested is the walk, not
    boto3: which objects the command decides to copy, and — the part that
    matters — which ones it leaves alone.
    """

    def __init__(self, **buckets):
        # {bucket: {key: (size, etag)}}
        self.buckets = {name: dict(items) for name, items in buckets.items()}
        self.copies = []
        self.deleted = []
        self.failing = set()

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self

    def paginate(self, Bucket, Prefix):  # noqa: N803 — boto3 spells them so
        items = [
            {"Key": key, "Size": size, "ETag": f'"{etag}"'}
            for key, (size, etag) in sorted(self.buckets[Bucket].items())
            if key.startswith(Prefix)
        ]
        # split in two, so a command that reads only the first page is caught
        yield {"Contents": items[:1]}
        yield {"Contents": items[1:]}

    def copy_object(self, Bucket, Key, CopySource):  # noqa: N803
        if Key in self.failing:
            raise EndpointConnectionError(endpoint_url="https://r2.example")

        self.copies.append(Key)
        self.buckets[Bucket][Key] = self.buckets[CopySource["Bucket"]][
            CopySource["Key"]
        ]

    def put_object(self, Bucket, Key, Body):  # noqa: N803
        self.buckets[Bucket][Key] = (len(Body), "put")

    def delete_object(self, Bucket, Key):  # noqa: N803
        self.deleted.append(Key)
        self.buckets[Bucket].pop(Key, None)


@override_settings(
    R2_BUCKET_NAME="main",
    R2_ENDPOINT_URL="https://r2.example",
    R2_BACKUP_BUCKET_NAME="backup",
    R2_BACKUP_ACCESS_KEY_ID="key",
    R2_BACKUP_SECRET_ACCESS_KEY="secret",
)
class BackupBucketTests(SimpleTestCase):
    """
    R2 has no versioning, so the copy is made by us — with one rule above all
    the others: this command never deletes anything, anywhere.
    """

    def run_backup(self, r2, **options):
        out = StringIO()
        with mock.patch.object(storage, "backup_client", return_value=r2):
            call_command("backup_files", stdout=out, stderr=out, **options)
        return out.getvalue()

    def test_it_copies_what_the_backup_does_not_have_yet(self):
        r2 = FakeR2(
            main={"files/1/a/one.pdf": (10, "aaa"), "files/1/b/two.pdf": (20, "bbb")},
            backup={"files/1/a/one.pdf": (10, "aaa")},
        )

        output = self.run_backup(r2)

        self.assertEqual(r2.copies, ["files/1/b/two.pdf"])
        self.assertIn("скопировано: 1", output)
        self.assertIn("пропущено (уже есть): 1", output)

    def test_running_it_twice_copies_nothing_the_second_time(self):
        r2 = FakeR2(main={"files/1/a/one.pdf": (10, "aaa")}, backup={})

        self.run_backup(r2)
        r2.copies.clear()
        output = self.run_backup(r2)

        self.assertEqual(r2.copies, [])
        self.assertIn("скопировано: 0", output)

    def test_what_was_deleted_in_the_main_bucket_stays_in_the_backup(self):
        """The whole reason the backup exists: it is not a mirror."""
        r2 = FakeR2(
            main={"files/1/a/one.pdf": (10, "aaa")},
            backup={"files/1/a/one.pdf": (10, "aaa"), "files/1/z/gone.pdf": (5, "zzz")},
        )

        output = self.run_backup(r2)

        self.assertIn("files/1/z/gone.pdf", r2.buckets["backup"])
        self.assertIn("осталось только в резерве: 1", output)

    def test_a_rewritten_object_is_copied_again(self):
        r2 = FakeR2(
            main={"files/1/a/one.pdf": (30, "ccc")},
            backup={"files/1/a/one.pdf": (10, "aaa")},
        )

        self.run_backup(r2)

        self.assertEqual(r2.copies, ["files/1/a/one.pdf"])

    def test_a_dry_run_copies_nothing(self):
        r2 = FakeR2(main={"files/1/a/one.pdf": (10, "aaa")}, backup={})

        output = self.run_backup(r2, dry_run=True)

        self.assertEqual(r2.copies, [])
        self.assertEqual(r2.buckets["backup"], {})
        self.assertIn("скопировался бы files/1/a/one.pdf", output)

    def test_an_empty_bucket_is_not_an_error(self):
        """Which is the state of production right now: no files uploaded yet."""
        r2 = FakeR2(main={}, backup={})

        output = self.run_backup(r2)

        self.assertIn("скопировано: 0", output)

    def test_restoring_walks_the_other_way(self):
        r2 = FakeR2(
            main={},
            backup={"files/1/a/one.pdf": (10, "aaa"), "files/1/b/two.pdf": (20, "bbb")},
        )

        self.run_backup(r2, restore=True)

        self.assertEqual(len(r2.buckets["main"]), 2)
        self.assertEqual(len(r2.buckets["backup"]), 2)

    def test_one_unhappy_object_does_not_cost_the_rest_of_the_run(self):
        r2 = FakeR2(
            main={"files/1/a/one.pdf": (10, "aaa"), "files/1/b/two.pdf": (20, "bbb")},
            backup={},
        )
        r2.failing.add("files/1/a/one.pdf")

        with self.assertRaises(CommandError) as refusal:
            self.run_backup(r2)

        # the failure is reported, but the other object did get through
        self.assertIn("не удалось", str(refusal.exception))
        self.assertEqual(r2.copies, ["files/1/b/two.pdf"])

    @override_settings(R2_BACKUP_BUCKET_NAME="")
    def test_it_refuses_when_the_backup_bucket_is_not_configured(self):
        with self.assertRaises(CommandError) as refusal:
            self.run_backup(FakeR2(main={}, backup={}))

        self.assertIn("R2_BACKUP_BUCKET_NAME", str(refusal.exception))


class NeedsCopyTests(SimpleTestCase):
    def item(self, size=10, etag="aaa"):
        return storage.Item(key="files/1/a/one.pdf", size=size, etag=etag)

    def test_a_missing_object_is_copied(self):
        self.assertTrue(storage.needs_copy(self.item(), None))

    def test_the_same_object_is_not(self):
        self.assertFalse(storage.needs_copy(self.item(), self.item()))

    def test_a_different_size_wins_over_everything(self):
        self.assertTrue(storage.needs_copy(self.item(size=20), self.item()))

    def test_a_different_etag_at_the_same_size_still_counts(self):
        self.assertTrue(storage.needs_copy(self.item(etag="bbb"), self.item()))

    def test_a_multipart_etag_is_not_compared(self):
        """Its dash means «md5 of the parts», and parts differ per upload."""
        self.assertFalse(storage.needs_copy(self.item(etag="aaa-2"), self.item()))


# --- names and keys ------------------------------------------------------------------


class StorageIsNeverRealTests(TestCase):
    def test_the_run_talks_to_memory_and_not_to_r2(self):
        """
        The guard for `config.testing.Runner`.

        It is here because it has already gone wrong: `seed_demo` uploads
        files, `test_seed_demo` runs it, and neither knew — thirty objects
        landed in the development bucket. A test suite that quietly writes to
        real storage is a test suite that will one day quietly delete from it.
        """
        self.assertEqual(type(storage.backend()).__name__, "InMemoryStorage")


class KeyTests(TestCase):
    def test_a_cyrillic_name_still_yields_a_usable_key(self):
        key = storage.build_key(7, "Контрольная работа №3.pdf")

        self.assertTrue(key.startswith("files/7/"))
        self.assertTrue(key.endswith(".pdf"))
        self.assertTrue(key.isascii())

    def test_a_path_in_the_name_cannot_climb_out_of_the_prefix(self):
        key = storage.build_key(7, "../../etc/passwd")

        self.assertTrue(key.startswith("files/7/"))
        self.assertNotIn("..", key)

    def test_the_download_header_carries_the_real_name(self):
        header = storage.content_disposition("Контрольная №3.pdf")

        self.assertIn("attachment;", header)
        self.assertIn("filename*=UTF-8''", header)
        self.assertIn("%D0%9A", header)


# --- the database dump ----------------------------------------------------------------


@override_settings(
    R2_ENDPOINT_URL="https://r2.example",
    R2_BACKUP_BUCKET_NAME="backup",
    R2_BACKUP_ACCESS_KEY_ID="key",
    R2_BACKUP_SECRET_ACCESS_KEY="secret",
)
class DatabaseDumpTests(SimpleTestCase):
    """
    Дамп базы уезжает в тот же резервный бакет, но под своим префиксом и со
    своим сроком жизни: копия двухмесячной давности — это уже не резерв.
    """

    def run_backup(self, r2, body=b"gzipped dump", **options):
        out = StringIO()
        options.setdefault("name", self.dump_name())
        with mock.patch.object(storage, "backup_client", return_value=r2):
            call_command(
                "backup_db", stdout=out, stderr=out, stdin=BytesIO(body), **options
            )
        return out.getvalue()

    def test_the_dump_lands_under_its_own_prefix(self):
        """
        Префикс `db/` — не косметика: `backup_files` ходит по `files/`, и с
        общим префиксом `--restore` вернул бы дампы в бакет вложений.
        """
        r2 = FakeR2(backup={})

        output = self.run_backup(r2)

        self.assertIn(self.dump_key(0), r2.buckets["backup"])
        self.assertIn("загружено", output)

    def test_an_empty_dump_is_refused(self):
        """Пустой объект в бакете выглядит копией — до того дня, когда нужен."""
        with self.assertRaises(CommandError):
            self.run_backup(FakeR2(backup={}), body=b"")

    def dump_name(self, days_ago: int = 0) -> str:
        """Имя дампа, снятого столько-то дней назад. Считается от сегодня:
        зашитая дата протухает вместе со сроком хранения — снятый «сегодня»
        дамп однажды оказался старше `keep_days` и удалил сам себя."""
        return f"lessons_{timezone.localdate() - timedelta(days=days_ago)}_0330.sql.gz"

    def dump_key(self, days_ago: int) -> str:
        return f"db/{self.dump_name(days_ago)}"

    def test_old_copies_go_and_fresh_ones_stay(self):
        old, fresh = self.dump_key(30), self.dump_key(1)
        r2 = FakeR2(backup={old: (10, "a"), fresh: (10, "b")})

        self.run_backup(r2, keep_days=7)

        self.assertEqual(r2.deleted, [old])
        self.assertIn(fresh, r2.buckets["backup"])

    def test_it_never_touches_the_attachments(self):
        """Вложения живут в том же бакете и удаляться не должны никогда."""
        old = self.dump_key(30)
        r2 = FakeR2(backup={"files/1/a/one.pdf": (10, "a"), old: (10, "b")})

        self.run_backup(r2, keep_days=1)

        self.assertEqual(r2.deleted, [old])
        self.assertIn("files/1/a/one.pdf", r2.buckets["backup"])

    def test_a_name_it_cannot_read_is_left_alone(self):
        """Не понял, что за объект, — не удаляй."""
        self.assertEqual(
            backup_db.expired(
                ["db/dump.sql.gz", "db/lessons_вчера.sql.gz"], 7, date(2030, 1, 1)
            ),
            [],
        )

    def test_a_slash_in_the_name_is_refused(self):
        with self.assertRaises(CommandError):
            self.run_backup(FakeR2(backup={}), name="../files/1/a/one.pdf")

    def test_without_backup_keys_it_says_so(self):
        with override_settings(R2_BACKUP_ACCESS_KEY_ID=""), self.assertRaises(
            CommandError
        ):
            self.run_backup(FakeR2(backup={}))
