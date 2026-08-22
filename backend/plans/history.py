"""
Журнал состояний плана: как он выглядел перед каждым изменением.

Отмена и откат чужих правок — одна механика, и вид у неё выбран не самый
очевидный. Первое, что приходит в голову, — писать **что сделали** и уметь
это обратить: создать↔удалить, переместить↔переместить назад. Выглядит
экономно, но у плана девять изменяющих операций (создание, правка, шаг,
`move_to`, разрез темы, удаление строки, удаление темы двумя способами,
импорт в трёх режимах, пакетное удаление), у каждой свои края, а «отменить
три шага» перемножает их.

Поэтому пишется **как было**: перед каждым действием кладётся компактный
снимок плана. Тогда «отменить последнее» — восстановить предыдущий снимок,
«отменить несколько» — снимок постарше, а откат правок администратора —
снимок, снятый перед его первой правкой. Одна операция вместо девяти
обратных, и она же обслуживает сравнение.

**Содержание лежит в снимке целиком.** Эталон (`PlanBaseline`) хранит
только структуру и отпечаток содержания — там это верно, утверждений за год
несколько и они про структуру. Здесь наоборот: главный случай отмены —
«удалил урок зря», а урок это прежде всего его текст. Строк без содержания
в плане большинство, так что снимок сотни строк весит десятки килобайт.

**Вложения журнал держит ссылкой.** Объект в бакете живёт, пока на него
ссылается хоть один `Attachment` (так устроена разделяемость с
библиотекой), — а удаление строки уносит её вложения каскадом. Поэтому
снимок ссылается на `StoredFile` сам: пока запись жива, объект не умирает,
восстановление создаёт вложения заново на тот же объект, а истечение
записи отпускает ссылку и включает обычную уборку.
"""

from django.conf import settings
from django.db import models, transaction

from .content import CONTENT_FIELDS

#: сколько снимков держать на курс ради обычной отмены. Отменяют почти
#: всегда последние минуты, и двадцати шагов на это с запасом
KEEP_PER_COURSE = 20

#: сколько дней держать снимок **вмешательства** — правки, сделанной не
#: ведущим курса. Тут счёт идёт не на минуты: учитель узнаёт о чужой правке,
#: когда откроет план, а это бывает и через неделю
KEEP_INTERVENTION_DAYS = 90


class PlanSnapshot(models.Model):
    """Как выглядел план курса непосредственно перед одним действием."""

    course = models.ForeignKey(
        "schedule.Course",
        related_name="snapshots",
        on_delete=models.CASCADE,
        verbose_name="course",
    )
    made_at = models.DateTimeField("taken at", auto_now_add=True, db_index=True)
    made_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="plan_snapshots",
        null=True,
        on_delete=models.SET_NULL,
        verbose_name="about to edit",
    )
    action = models.CharField(
        "what happened next",
        max_length=32,
        help_text="Машинный код действия: по нему кнопка отмены называет себя.",
    )
    detail = models.CharField(
        "what it touched",
        max_length=200,
        blank=True,
        help_text="Название строки или файла — чтобы «отменить» называло, что именно.",
    )
    by_lead = models.BooleanField(
        "made by the lead teacher",
        default=True,
        help_text=(
            "Правил ли курс его собственный ведущий. Снимок чужой правки "
            "живёт дольше и показывается учителю пометкой: он про неё иначе "
            "не узнает."
        ),
    )

    class Meta:
        verbose_name = "plan snapshot"
        verbose_name_plural = "plan snapshots"
        ordering = ("-made_at", "-id")
        indexes = [models.Index(fields=["course", "-made_at"])]

    def __str__(self):
        return f"{self.course} — {self.action} @ {self.made_at:%Y-%m-%d %H:%M}"


class PlanSnapshotRow(models.Model):
    """
    Строка снимка — плоская, как у эталона.

    `node_id` хранится числом, а не связью: узел могут удалить, и именно
    это удаление снимок должен пережить, чтобы вернуть строку с её
    прежним идентификатором.
    """

    snapshot = models.ForeignKey(
        PlanSnapshot,
        related_name="rows",
        on_delete=models.CASCADE,
        verbose_name="snapshot",
    )
    node_id = models.PositiveIntegerField("plan node id")
    parent_node_id = models.PositiveIntegerField(
        "parent node id", null=True, blank=True
    )
    position = models.PositiveIntegerField("position")
    is_section = models.BooleanField("section", default=False)
    title = models.CharField("title", max_length=200)
    note = models.TextField("note", blank=True)
    objectives = models.TextField("objectives", blank=True)
    body = models.TextField("body", blank=True)
    formative = models.TextField("formative check", blank=True)
    homework = models.TextField("homework", blank=True)

    class Meta:
        verbose_name = "plan snapshot row"
        verbose_name_plural = "plan snapshot rows"
        ordering = ("position", "id")

    def __str__(self):
        return self.title


class PlanSnapshotFile(models.Model):
    """
    Вложение строки в снимке — и держатель ссылки на объект в бакете.

    `PROTECT` тут не про целостность ради целостности: пока снимок жив,
    объект не должен исчезнуть из R2, иначе откат вернул бы строку с
    вложением, которое отвечает 404.
    """

    row = models.ForeignKey(
        PlanSnapshotRow,
        related_name="files",
        on_delete=models.CASCADE,
        verbose_name="row",
    )
    stored_file = models.ForeignKey(
        "files.StoredFile",
        related_name="snapshot_links",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        verbose_name="stored file",
    )
    kind = models.CharField("kind", max_length=8)
    title = models.CharField("title", max_length=200, blank=True)
    url = models.URLField("external address", blank=True, max_length=500)

    class Meta:
        verbose_name = "plan snapshot attachment"
        verbose_name_plural = "plan snapshot attachments"
        ordering = ("id",)


ROW_FIELDS = ("position", "is_section", "title", "note", *CONTENT_FIELDS)


# --- снятие -------------------------------------------------------------------


def lead_of(course_id):
    """Кто ведёт курс — по нему решается, вмешательство это или своя правка."""
    from schedule.models import CourseAssignment

    row = CourseAssignment.objects.filter(course_id=course_id).first()
    return row.teacher_id if row is not None else None


@transaction.atomic
def take(course, user, action: str, detail: str = "") -> PlanSnapshot:
    """
    Снять снимок плана — прямо перед тем, как его изменят.

    Зовётся из пишущих путей, а не из сигнала: сигнал не знает, что за
    действие последует, а без этого кнопка отмены не сможет назвать себя
    («Отменить: удаление темы „Векторы“»). Полнота вызовов сторожится
    отдельно — `plans/test_history_wiring.py`.
    """
    from files.models import Attachment
    from .models import PlanNode

    snapshot = PlanSnapshot.objects.create(
        course=course,
        made_by=user if getattr(user, "is_authenticated", False) else None,
        action=action,
        detail=detail[:200],
        by_lead=lead_of(course.pk) == getattr(user, "pk", None),
    )

    nodes = list(PlanNode.objects.filter(course=course))
    rows = PlanSnapshotRow.objects.bulk_create(
        [
            PlanSnapshotRow(
                snapshot=snapshot,
                node_id=node.pk,
                parent_node_id=node.parent_id,
                **{field: getattr(node, field) for field in ROW_FIELDS},
            )
            for node in nodes
        ]
    )

    by_node = {row.node_id: row for row in rows}
    attachments = Attachment.objects.filter(plan_row__course=course)
    PlanSnapshotFile.objects.bulk_create(
        [
            PlanSnapshotFile(
                row=by_node[item.plan_row_id],
                stored_file_id=item.stored_file_id,
                kind=item.kind,
                title=item.title,
                url=item.url,
            )
            for item in attachments
            if item.plan_row_id in by_node
        ]
    )

    prune(course)
    return snapshot


def prune(course) -> int:
    """
    Убрать снимки, которые уже никому не нужны.

    Границы разные, потому что разные и вопросы. Свою правку отменяют
    минутами позже — на это хватает последних `KEEP_PER_COURSE` шагов. А про
    чужую учитель узнаёт, когда откроет план, и это бывает через неделю,
    поэтому снимки вмешательства живут `KEEP_INTERVENTION_DAYS` дней.

    Чистится при записи, а не по расписанию: cron ради этого заводить не
    из-за чего, а «сотый снимок вытесняет первый» — ровно то поведение,
    которого от стека и ждут.
    """
    from datetime import timedelta

    from django.utils import timezone

    fresh = list(
        PlanSnapshot.objects.filter(course=course)
        .order_by("-made_at", "-id")
        .values_list("pk", flat=True)[:KEEP_PER_COURSE]
    )
    edge = timezone.now() - timedelta(days=KEEP_INTERVENTION_DAYS)

    doomed = (
        PlanSnapshot.objects.filter(course=course)
        .exclude(pk__in=fresh)
        .exclude(by_lead=False, made_at__gte=edge)
    )
    return doomed.delete()[0]


# --- восстановление -----------------------------------------------------------


@transaction.atomic
def restore(snapshot) -> dict:
    """
    Вернуть план в состояние снимка.

    Строки узнаются по `node_id` — как при синхронизации импорта, и по той
    же причине: это единственный способ отличить «строку переименовали» от
    «одну удалили, другую завели». Разница с импортом в том, что удалённую
    строку здесь **воскрешают с прежним id**: за ней могут стоять
    вложения, эталон и ссылки, и новая строка с новым номером — это не она.

    Порядок внутри записи важен: сперва темы (уроку под новой темой нужен
    её id), потом уроки, и только потом удаляется лишнее — иначе каскад
    унёс бы уроки удаляемой темы вместе с ней.
    """
    from files.models import Attachment
    from .models import PlanNode

    course = snapshot.course
    wanted = list(snapshot.rows.prefetch_related("files"))
    alive = {node.pk: node for node in PlanNode.objects.filter(course=course)}

    created, updated = 0, 0
    # темы первыми: на них ссылаются уроки
    for row in sorted(wanted, key=lambda item: not item.is_section):
        node = alive.get(row.node_id)
        values = {field: getattr(row, field) for field in ROW_FIELDS}

        if node is None:
            PlanNode.objects.create(
                pk=row.node_id,
                course=course,
                parent_id=row.parent_node_id,
                **values,
            )
            created += 1
            continue

        changed = [
            field for field in ROW_FIELDS if getattr(node, field) != values[field]
        ]
        if node.parent_id != row.parent_node_id:
            node.parent_id = row.parent_node_id
            changed.append("parent")
        if changed:
            for field in ROW_FIELDS:
                setattr(node, field, values[field])
            node.save(update_fields=changed)
            updated += 1

    keep = {row.node_id for row in wanted}
    doomed = [pk for pk in alive if pk not in keep]
    # уроки раньше тем: иначе каскад унесёт чужих детей
    PlanNode.objects.filter(pk__in=doomed, is_section=False).delete()
    PlanNode.objects.filter(pk__in=doomed).delete()

    restored_files = restore_files(wanted)

    return {
        "created": created,
        "updated": updated,
        "deleted": len(doomed),
        "files": restored_files,
    }


def restore_files(rows) -> int:
    """
    Вернуть вложения строк — те, что были на момент снимка.

    Объект в бакете жив, потому что на него ссылается сам снимок
    (`PlanSnapshotFile.stored_file`, `PROTECT`), так что воскрешать нужно
    только ссылку. Вложения строки заменяются целиком: половина списка
    хуже, чем список целиком, а разбираться, какое из них то же самое,
    нечем — своего устойчивого id у вложения в снимке нет.
    """
    from files.models import Attachment

    made = 0
    for row in rows:
        wanted = list(row.files.all())
        current = Attachment.objects.filter(plan_row_id=row.node_id)

        same = [
            (item.kind, item.stored_file_id, item.url, item.title) for item in current
        ]
        expected = [
            (item.kind, item.stored_file_id, item.url, item.title) for item in wanted
        ]
        if same == expected:
            continue

        current.delete()
        for position, item in enumerate(wanted):
            Attachment.objects.create(
                plan_row_id=row.node_id,
                kind=item.kind,
                stored_file_id=item.stored_file_id,
                url=item.url,
                title=item.title,
                position=position,
            )
            made += 1

    return made
