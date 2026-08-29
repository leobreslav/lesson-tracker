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

from config.errors import Codes, api_error

from .content import CONTENT_FIELDS
from .owning import exactly_one_owner, owner_of

#: сколько снимков держать на один план ради обычной отмены. Отменяют почти
#: всегда последние минуты, и двадцати шагов на это с запасом.
#:
#: Имя было `KEEP_PER_COURSE`, и оно перестало быть правдой вместе со вторым
#: владельцем: планов теперь два вида, а граница у них одна.
KEEP_PER_PLAN = 20

#: сколько дней держать снимок **вмешательства** — правки, сделанной не
#: ведущим курса. Тут счёт идёт не на минуты: учитель узнаёт о чужой правке,
#: когда откроет план, а это бывает и через неделю.
#:
#: У шаблона вмешательства не бывает вовсе: правит его только автор
#: (`writable_templates`), значит всякая правка своя, и эта граница до него
#: просто не доходит.
KEEP_INTERVENTION_DAYS = 90


class PlanSnapshot(models.Model):
    """Как выглядел план непосредственно перед одним действием."""

    course = models.ForeignKey(
        "schedule.Course",
        related_name="snapshots",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name="course",
    )
    #: Второй владелец, тот же, что у самой строки плана (`plans/owning.py`):
    #: шаблон с полки правят тем же экраном, значит и отменяют тем же журналом.
    #: Второй журнал рядом с этим был бы второй механикой отмены — у
    #: расписания она своя по делу (другая единица, другая глубина, свои девять
    #: операций), а тут предмет один и тот же, дерево уроков.
    template = models.ForeignKey(
        "library.PlanTemplate",
        related_name="snapshots",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name="library template",
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
        indexes = [
            models.Index(fields=["course", "-made_at"]),
            models.Index(fields=["template", "-made_at"], name="snapshot_template_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=exactly_one_owner(),
                name="plan_snapshot_has_exactly_one_owner",
            ),
        ]

    @property
    def owner(self):
        """Чей это снимок — курса или шаблона; см. `plans/owning.py`."""
        return owner_of(self)

    def __str__(self):
        whose = self.course or self.template
        return f"{whose} — {self.action} @ {self.made_at:%Y-%m-%d %H:%M}"


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
    # стояла ли она **в тексте**: без этого отмена вернула бы картинку
    # строкой в списке материалов — при том, что в тексте она нарисована
    inline = models.BooleanField("inline in the text", default=False)
    title = models.CharField("title", max_length=200, blank=True)
    url = models.URLField("external address", blank=True, max_length=500)

    class Meta:
        verbose_name = "plan snapshot attachment"
        verbose_name_plural = "plan snapshot attachments"
        ordering = ("id",)


class PlanSnapshotIntroduction(models.Model):
    """
    Пометка «этот урок вводит это понятие» в снимке.

    Живёт она в `bank.Introduction` и держится за строку плана `CASCADE`:
    удалили строку — пометка ушла. Отмена возвращала строку с прежним
    номером, а пометку возвращать было неоткуда, её больше не было нигде.
    Вложениям повезло, этой связи нет — и разница между ними была не
    решением, а невнимательностью.

    `CASCADE` на теге, а не `PROTECT`, как у файла, — и причина ровно
    обратная той. Файл `PROTECT`ится потому, что объект в бакете должен
    дожить до отката: удалить его значит вернуть строку с вложением, которое
    отвечает 404. Тег же удаляют из задачника целиком, и держать его живым
    ради двадцати снимков значило бы воскрешать понятие, которое из проекта
    убрали.

    Курс хранится свой, а не берётся у снимка. Совпадают они всегда, но
    «всегда» тут держится на допущении о чужом приложении, а этот файл на
    допущениях уже обжигался.
    """

    row = models.ForeignKey(
        PlanSnapshotRow,
        related_name="introductions",
        on_delete=models.CASCADE,
        verbose_name="row",
    )
    course = models.ForeignKey(
        "schedule.Course",
        related_name="snapshot_introductions",
        on_delete=models.CASCADE,
        verbose_name="course",
    )
    tag = models.ForeignKey(
        "bank.Tag",
        related_name="snapshot_introductions",
        on_delete=models.CASCADE,
        verbose_name="tag introduced here",
    )

    class Meta:
        verbose_name = "plan snapshot introduction"
        verbose_name_plural = "plan snapshot introductions"
        ordering = ("id",)


ROW_FIELDS = ("position", "is_section", "title", "note", *CONTENT_FIELDS)


# --- снятие -------------------------------------------------------------------


def lead_of(course_id):
    """Кто ведёт курс — по нему решается, вмешательство это или своя правка."""
    from schedule.models import CourseAssignment

    row = CourseAssignment.objects.filter(course_id=course_id).first()
    return row.teacher_id if row is not None else None


@transaction.atomic
def take(owner, user, action: str, detail: str = "") -> PlanSnapshot:
    """
    Снять снимок плана — прямо перед тем, как его изменят.

    Зовётся из пишущих путей, а не из сигнала: сигнал не знает, что за
    действие последует, а без этого кнопка отмены не сможет назвать себя
    («Отменить: удаление темы „Векторы“»). Полнота вызовов сторожится
    отдельно — `plans/test_history_wiring.py`.

    `owner` — чей это план (`plans/owning.PlanOwner`): курс или шаблон с
    полки. Механика у них одна, и это не экономия: предмет один и тот же —
    дерево уроков, — а вторая механика отмены рядом с первой означала бы, что
    однажды они разойдутся в том, что считают шагом.
    """
    from bank.models import Introduction
    from files.models import Attachment
    from .models import PlanNode

    snapshot = PlanSnapshot.objects.create(
        **owner.lookup,
        made_by=user if getattr(user, "is_authenticated", False) else None,
        action=action,
        detail=detail[:200],
        # У шаблона правка всегда своя: править его вправе только автор, и
        # «вмешательство» там не значит ничего. Спрашивать про ведущего
        # некого — назначений у полки нет вовсе.
        by_lead=(
            True
            if owner.is_template
            else lead_of(owner.id) == getattr(user, "pk", None)
        ),
    )

    nodes = list(PlanNode.objects.filter(**owner.lookup))
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
    # по самим строкам, а не по владельцу: строки уже выбраны, второй вопрос
    # к базе про то же самое отличался бы от первого только формулировкой — и
    # разошёлся бы с ним в первый же раз, когда у плана появится третий вид
    attachments = Attachment.objects.filter(plan_row_id__in=by_node)
    PlanSnapshotFile.objects.bulk_create(
        [
            PlanSnapshotFile(
                row=by_node[item.plan_row_id],
                stored_file_id=item.stored_file_id,
                kind=item.kind,
                inline=item.inline,
                title=item.title,
                url=item.url,
            )
            for item in attachments
            if item.plan_row_id in by_node
        ]
    )

    # тем же способом, что и вложения, и по той же причине: пометка задачника
    # держится за строку каскадом, и удаление строки уносит её насовсем
    introductions = Introduction.objects.filter(node_id__in=by_node)
    PlanSnapshotIntroduction.objects.bulk_create(
        [
            PlanSnapshotIntroduction(
                row=by_node[item.node_id],
                course_id=item.course_id,
                tag_id=item.tag_id,
            )
            for item in introductions
            if item.node_id in by_node
        ]
    )

    prune(owner)
    return snapshot


def prune(owner) -> int:
    """
    Убрать снимки, которые уже никому не нужны.

    Границы разные, потому что разные и вопросы. Свою правку отменяют
    минутами позже — на это хватает последних `KEEP_PER_PLAN` шагов. А про
    чужую учитель узнаёт, когда откроет план, и это бывает через неделю,
    поэтому снимки вмешательства живут `KEEP_INTERVENTION_DAYS` дней.

    Считается это **по владельцу**, а не по всем снимкам разом: у полки и у
    курса свои двадцать шагов, и правка шаблона не должна вытеснять отмену в
    курсе. У шаблона вторая граница не срабатывает никогда — снимков
    вмешательства там не бывает.

    Чистится при записи, а не по расписанию: cron ради этого заводить не
    из-за чего, а «двадцать первый снимок вытесняет первый» — ровно то
    поведение, которого от стека и ждут.
    """
    from datetime import timedelta

    from django.utils import timezone

    fresh = list(
        PlanSnapshot.objects.filter(**owner.lookup)
        .order_by("-made_at", "-id")
        .values_list("pk", flat=True)[:KEEP_PER_PLAN]
    )
    edge = timezone.now() - timedelta(days=KEEP_INTERVENTION_DAYS)

    doomed = (
        PlanSnapshot.objects.filter(**owner.lookup)
        .exclude(pk__in=fresh)
        .exclude(by_lead=False, made_at__gte=edge)
    )
    return doomed.delete()[0]


# --- восстановление -----------------------------------------------------------


def refuse_if_undo_loses_record(doomed) -> None:
    """
    Отмена не уносит проведённые строки — как их не уносит ничто другое.

    Строку, по которой провели занятие, не удаляют: за ней записан час, и
    `Slot.lesson` — `SET_NULL`, то есть удаление не отказывает, а **молча**
    развязывает связь. Четыре двери к этому удалению закрыты давно —
    одиночное удаление и пакетное (`plan_delete_taught`), импорт в обоих
    режимах и взятие с полки (`plan_import_taught`), — а эта была открыта:
    завели строку после снимка, провели по ней урок, нажали отмену, и запись
    об уроке исчезала, не оставив следа даже в пост-условии. `broken_record`
    её не ловит: он ищет незакрытый час **среди закрытых**, а развязанный
    последний час дыры не образует.

    Отказ стоит здесь, а не во вьюхе, ровно затем, чтобы пятой открытой
    двери не появилось: закрыт сам проход, а не подходы к нему. Так же
    устроена отмена в расписании (`schedule/history.py`,
    `slot_undo_would_lose_work`) — предмет разный, а урок один и тот же.

    У шаблона занятий не бывает вовсе, и вопрос впустую стоит один
    индексированный запрос. Ветка «а если это полка, то не спрашиваем» стоила
    бы дороже: она держится на допущении, а допущения в этом файле уже
    ошибались.
    """
    if not doomed:
        return

    from schedule.models import Slot

    taught = (
        Slot.objects.filter(lesson_id__in=doomed).select_related("lesson").first()
    )
    if taught is not None:
        api_error(
            Codes.PLAN_UNDO_WOULD_LOSE_RECORD,
            f"«{taught.lesson.title}» was taught on {taught.date}: undoing "
            "would delete the row and its record with it.",
            field="snapshot",
            title=taught.lesson.title,
            date=str(taught.date),
        )


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

    owner = snapshot.owner
    wanted = list(snapshot.rows.prefetch_related("files", "introductions"))
    alive = {node.pk: node for node in PlanNode.objects.filter(**owner.lookup)}

    created, updated = 0, 0
    # темы первыми: на них ссылаются уроки
    for row in sorted(wanted, key=lambda item: not item.is_section):
        node = alive.get(row.node_id)
        values = {field: getattr(row, field) for field in ROW_FIELDS}

        if node is None:
            PlanNode.objects.create(
                pk=row.node_id,
                **owner.lookup,
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
    refuse_if_undo_loses_record(doomed)
    # уроки раньше тем: иначе каскад унесёт чужих детей
    PlanNode.objects.filter(pk__in=doomed, is_section=False).delete()
    PlanNode.objects.filter(pk__in=doomed).delete()

    restored_files = restore_files(wanted)
    restored_marks = restore_introductions(wanted)

    return {
        "created": created,
        "updated": updated,
        "deleted": len(doomed),
        "files": restored_files,
        "introductions": restored_marks,
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
            (item.kind, item.stored_file_id, item.url, item.title, item.inline)
            for item in current
        ]
        expected = [
            (item.kind, item.stored_file_id, item.url, item.title, item.inline)
            for item in wanted
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
                inline=item.inline,
                title=item.title,
                position=position,
            )
            made += 1

    return made


def restore_introductions(rows) -> int:
    """
    Вернуть разметку задачника — ту, что была на момент снимка.

    Состояние восстанавливается целиком, как у вложений: что было отмечено,
    отмечено снова; что отметили после снимка, снимается. Снимок для этого
    полон — `take` берёт пометки по всем строкам плана, а пометка курса
    ничем, кроме строки его же плана, висеть не может.

    Ставится она через `bank.topics.introduce`, а не записью в таблицу. Там
    записано правило, которое иначе пришлось бы повторить здесь: понятие
    вводится однажды, и повторная отметка **переносит** её, а не заводит
    вторую. Копия этого правила разошлась бы с оригиналом молча, а расплата
    за расхождение — отказ базы по `one_lesson_introduces_a_tag` посреди
    отмены.
    """
    from bank.models import Introduction, Tag
    from bank.topics import introduce
    from schedule.models import Course

    from .models import PlanNode

    #: (курс, тег) → на какой строке пометка стояла
    wanted = {
        (mark.course_id, mark.tag_id): row.node_id
        for row in rows
        for mark in row.introductions.all()
    }

    # лишнее — пометки на строках этого плана, которых в снимке не было
    here = [row.node_id for row in rows]
    extra = [
        mark.pk
        for mark in Introduction.objects.filter(node_id__in=here)
        if (mark.course_id, mark.tag_id) not in wanted
    ]
    Introduction.objects.filter(pk__in=extra).delete()

    if not wanted:
        return 0

    courses = Course.objects.in_bulk({course for course, _ in wanted})
    tags = Tag.objects.in_bulk({tag for _, tag in wanted})
    nodes = PlanNode.objects.in_bulk(set(wanted.values()))

    made = 0
    for (course_id, tag_id), node_id in wanted.items():
        course, tag, node = courses.get(course_id), tags.get(tag_id), nodes.get(node_id)
        # тега может уже не быть: его удаляют из задачника целиком, и
        # воскрешать понятие, которое из проекта убрали, отмена не должна
        if course is None or tag is None or node is None:
            continue
        introduce(course, node, tag)
        made += 1

    return made
