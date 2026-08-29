"""
Журнал состояний расписания: каким оно было перед каждым изменением.

Вид у отмены выбран не самый очевидный, и выбран он по тому же доводу, что
у плана (`plans/history.py`). Первое, что приходит в голову, — писать **что
сделали** и уметь это обратить: завели↔удалить, перенесли↔перенести назад,
скопировали неделю↔снести скопированное. У расписания изменяющих операций
девять (создание, правка, удаление, ряд до даты, копирование, перенос,
кабинет ряду, массовая уборка, закрытие долгов пачкой), у каждой свои края,
а «отменить три шага» их перемножает.

Поэтому пишется **как было**: перед каждым действием кладётся снимок слотов
курса. Тогда «отменить последнее» — вернуть предыдущий снимок, и операция
одна вместо девяти обратных.

**Единица снимка — курс, и это не выбор, а следствие.** Год у курса один
(`Course.year`), а слот, чей год отличается от года курса, отклоняется
сериализатором (`slot_year_mismatch`), — значит «слоты курса» и есть
замкнутое множество, которое можно вернуть целиком.

**Действие, задевшее несколько курсов, кладёт несколько снимков под одной
партией** (`batch`). Таких два: копирование в школьном виде и массовая
уборка пустых клеток. Отмена по партии возвращает их все разом — вернуть
половину значит оставить расписание в состоянии, которого не было никогда.

**На слоте висит чужая работа, и снимок обязан её пережить.** Посещаемость
(`Attendance`) уходит вместе со слотом каскадом, а работы (`Work.slot`)
теряют привязку по `SET_NULL`. Поэтому строка снимка несёт и то и другое.

**Восстанавливаются они только у воскрешённых слотов**, и это важнее, чем
кажется. Отменяют действие **с расписанием**; если слот всё это время стоял
на месте, а в журнале ему после снимка отметили присутствие, то откат
расписания не вправе стереть эту отметку — человек её не отменял. Так что
посещаемость возвращается ровно там, где её унёс каскад: у клетки, которую
пришлось создать заново.
"""

from config.errors import Codes, api_error
from django.conf import settings
from django.db import models, transaction

# Кто ведёт курс — вопрос один на оба журнала, и ответ на него один.
# Определён он у плана раньше и живёт там; заводить второй значит завести
# и второй способ разойтись.
from plans.history import lead_of

#: Сколько снимков держать на курс.
#:
#: Отменяют тут **один** шаг, и глубже не ходят: ручка номера снимка не
#: принимает вовсе. Больше одного держится ради самой отмены — она тоже шаг
#: и тоже пишется в журнал, иначе «вернул не то» становилось бы тупиком, — и
#: ради второго человека: пока один правит, другой мог нажать своё.
#:
#: Двадцать, как у плана, тут не нужны: у плана отменяют и чужую правку
#: недельной давности, а расписание правят и отменяют в одну минуту.
KEEP_PER_COURSE = 5

#: сколько дней держать снимок **вмешательства** — правки, сделанной не
#: ведущим курса. Расписание чужого курса чинит администратор, и учитель
#: узнаёт об этом, когда откроет неделю, а это бывает и через неделю
KEEP_INTERVENTION_DAYS = 90

#: поля слота, которые снимок возвращает. `year` сюда не входит намеренно:
#: он равен году курса, и снимок, умеющий его переписать, выражал бы
#: состояние, которого сериализатор не допускает
ROW_FIELDS = (
    "date",
    "lesson_number",
    "is_cancelled",
    "is_extra",
    "reason",
    "lesson_id",
    "taught_by_id",
    "room_id",
)


class SlotSnapshot(models.Model):
    """Каким было расписание курса непосредственно перед одним действием."""

    course = models.ForeignKey(
        "schedule.Course",
        related_name="slot_snapshots",
        on_delete=models.CASCADE,
        verbose_name="course",
    )
    made_at = models.DateTimeField("taken at", auto_now_add=True, db_index=True)
    made_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="slot_snapshots",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="made by",
    )
    action = models.CharField("action", max_length=32)
    detail = models.CharField("what exactly", max_length=200, blank=True)
    #: правку сделал ведущий курса, а не кто-то со стороны. По этому полю
    #: расходятся сроки хранения — см. `prune`
    by_lead = models.BooleanField("by the course lead", default=True)
    #: одно действие на несколько курсов: снимки под одной партией
    #: отменяются вместе
    batch = models.UUIDField("batch", db_index=True)

    class Meta:
        verbose_name = "schedule snapshot"
        verbose_name_plural = "schedule snapshots"
        ordering = ("-made_at", "-id")

    def __str__(self):
        return f"{self.course_id} · {self.action} · {self.made_at:%Y-%m-%d %H:%M}"


class SlotSnapshotRow(models.Model):
    """Один слот в снимке — со своим прежним номером."""

    snapshot = models.ForeignKey(
        SlotSnapshot,
        related_name="rows",
        on_delete=models.CASCADE,
        verbose_name="snapshot",
    )
    #: номер самого слота, а не связь: слот могут удалить, и именно это
    #: удаление снимок обязан пережить, чтобы о нём рассказать
    slot_id = models.PositiveIntegerField("slot id", db_index=True)
    date = models.DateField("date")
    lesson_number = models.PositiveSmallIntegerField("number")
    is_cancelled = models.BooleanField("cancelled", default=False)
    is_extra = models.BooleanField("extra lesson", default=False)
    reason = models.CharField("reason", max_length=200, blank=True)
    lesson_id = models.PositiveIntegerField("plan row", null=True, blank=True)
    taught_by_id = models.PositiveIntegerField("taught by", null=True, blank=True)
    room_id = models.PositiveIntegerField("room", null=True, blank=True)
    #: что висело на слоте: посещаемость уходит каскадом, работы теряют
    #: привязку. Списком, а не своими моделями, — внешних ресурсов тут нет,
    #: держать в живых нечего, и `PROTECT`, ради которого у плана заведена
    #: отдельная таблица вложений, здесь не нужен
    attendance = models.JSONField("attendance", default=list, blank=True)
    works = models.JSONField("works set here", default=list, blank=True)

    class Meta:
        verbose_name = "schedule snapshot row"
        verbose_name_plural = "schedule snapshot rows"
        ordering = ("date", "lesson_number", "id")

    def __str__(self):
        return f"{self.date} №{self.lesson_number}"


# --- снятие -------------------------------------------------------------------


@transaction.atomic
def take(course, user, action: str, detail: str = "", batch=None) -> SlotSnapshot:
    """
    Снять снимок расписания курса — прямо перед тем, как его изменят.

    Зовётся из пишущих путей, а не из сигнала: сигнал не знает, что за
    действие последует, а без этого кнопка отмены не сможет назвать себя
    («Отменить: копирование недели»). Полноту вызовов стережёт
    `schedule/test_history_wiring.py`.

    `batch` передают, когда одно действие идёт по нескольким курсам: тогда
    у снимков общий номер партии и отменяются они вместе.
    """
    import uuid

    from works.models import Work

    from .models import Attendance, Slot

    snapshot = SlotSnapshot.objects.create(
        course=course,
        made_by=user if getattr(user, "is_authenticated", False) else None,
        action=action,
        detail=detail[:200],
        by_lead=lead_of(course.pk) == getattr(user, "pk", None),
        batch=batch or uuid.uuid4(),
    )

    slots = list(Slot.objects.filter(course=course))
    ids = [slot.pk for slot in slots]

    presence = {}
    for row in Attendance.objects.filter(slot_id__in=ids):
        presence.setdefault(row.slot_id, []).append(
            {
                "student": row.student_id,
                "status": row.status,
                "note": row.note,
                "marked_by": row.marked_by_id,
            }
        )

    works = {}
    for work_id, slot_id in Work.objects.filter(slot_id__in=ids).values_list(
        "id", "slot_id"
    ):
        works.setdefault(slot_id, []).append(work_id)

    SlotSnapshotRow.objects.bulk_create(
        [
            SlotSnapshotRow(
                snapshot=snapshot,
                slot_id=slot.pk,
                attendance=presence.get(slot.pk, []),
                works=works.get(slot.pk, []),
                **{field: getattr(slot, field) for field in ROW_FIELDS},
            )
            for slot in slots
        ]
    )

    prune(course)
    return snapshot


def prune(course) -> int:
    """
    Убрать снимки, которые уже никому не нужны.

    Границы разные, потому что разные и вопросы. Свою правку отменяют
    минутами позже — на это хватает последних `KEEP_PER_COURSE` шагов. А про
    чужую учитель узнаёт, когда откроет расписание, и это бывает через
    неделю, поэтому снимки вмешательства живут `KEEP_INTERVENTION_DAYS` дней.

    Чистится при записи, а не по расписанию: cron ради этого заводить не
    из-за чего, а «двадцать первый снимок вытесняет первый» — ровно то
    поведение, которого от стека и ждут.
    """
    from datetime import timedelta

    from django.utils import timezone

    fresh = list(
        SlotSnapshot.objects.filter(course=course)
        .order_by("-made_at", "-id")
        .values_list("pk", flat=True)[:KEEP_PER_COURSE]
    )
    edge = timezone.now() - timedelta(days=KEEP_INTERVENTION_DAYS)

    doomed = (
        SlotSnapshot.objects.filter(course=course)
        .exclude(pk__in=fresh)
        .exclude(by_lead=False, made_at__gte=edge)
    )
    return doomed.delete()[0]


# --- восстановление -----------------------------------------------------------


@transaction.atomic
def restore(snapshot) -> dict:
    """
    Вернуть расписание курса в состояние снимка.

    Слоты узнаются по прежнему номеру, и удалённый **воскрешается с тем же
    id**: на нём висят посещаемость и работы, а клетка с новым номером —
    это уже не она. Тот же довод, по которому строка плана возвращается со
    своим id.

    Порядок важен: сначала убирается лишнее, потом правится уцелевшее и
    только потом создаётся недостающее. Иначе воскрешённая клетка упёрлась
    бы в `unique_together (course, date, lesson_number)` — место, на котором
    она стояла, к этому моменту могло быть занято тем, что действие туда
    поставило.
    """
    from .models import Slot

    course = snapshot.course
    rows = list(snapshot.rows.all())
    wanted = {row.slot_id: row for row in rows}

    live = {slot.pk: slot for slot in Slot.objects.filter(course=course)}

    # 1. лишнее — то, чего в снимке не было
    extra = [pk for pk in live if pk not in wanted]
    if extra:
        doomed = Slot.objects.filter(pk__in=extra)
        # Отмена — не задняя дверь в обход правила «занятие с записью не
        # удаляют». Клетка, заведённая отменяемым действием, обычно пуста,
        # но между снимком и нажатием на ней могли отметить присутствие или
        # записать урок — вторым человеком или в соседней вкладке. Молча
        # унести это значит потерять работу, которую никто не отменял.
        #
        # Что считается записью, спрашиваем у самой модели
        # (`empty_conditions`): третье определение «пустоты» разошлось бы с
        # двумя первыми молча.
        #
        # Именно `empty_conditions`, а не `sweepable`: тот считает записью
        # ещё и «дополнительный», и «отменённый», — и правильно делает,
        # массовая чистка не должна стирать историю. Но отмену это заперло
        # бы намертво: дополнительный час **создаёт сам перенос**, и не дать
        # его убрать значит не дать отменить перенос вовсе. Флаги ставит
        # действие, а запись оставляет человек — снимаем первое, бережём
        # второе.
        busy = doomed.exclude(pk__in=doomed.filter(**Slot.empty_conditions()).values("pk"))
        first = busy.order_by("date", "lesson_number").first()
        if first is not None:
            api_error(
                Codes.SLOT_UNDO_WOULD_LOSE_WORK,
                f"{first.date} lesson {first.lesson_number} has something "
                "recorded on it: undoing would take that away.",
                field="snapshot",
                date=str(first.date),
                number=first.lesson_number,
            )
        doomed.delete()

    # 2. уцелевшее — вернуть поля
    changed = 0
    for pk, row in wanted.items():
        slot = live.get(pk)
        if slot is None:
            continue
        fields = [field for field in ROW_FIELDS if getattr(slot, field) != getattr(row, field)]
        if fields:
            for field in fields:
                setattr(slot, field, getattr(row, field))
            slot.save(update_fields=fields)
            changed += 1

    # 3. недостающее — создать заново с прежним номером
    missing = [row for row in rows if row.slot_id not in live]
    if missing:
        Slot.objects.bulk_create(
            [
                Slot(
                    pk=row.slot_id,
                    course=course,
                    year_id=course.year_id,
                    **{field: getattr(row, field) for field in ROW_FIELDS},
                )
                for row in missing
            ]
        )
        restore_hangers(missing)

    return {
        "restored": len(rows),
        "created": len(missing),
        "deleted": len(extra),
        "changed": changed,
    }


def restore_hangers(rows) -> dict:
    """
    Вернуть на воскрешённые слоты то, что висело на них.

    Только на воскрешённые, и это правило, а не экономия: отменяют действие
    **с расписанием**. Клетка, простоявшая всё это время на месте, могла за
    те же минуты получить отметку в журнале, и откат расписания не вправе
    её стереть — человек отменял не это.
    """
    from works.models import Work

    from .models import Attendance

    presence = [
        Attendance(
            slot_id=row.slot_id,
            student_id=item["student"],
            status=item["status"],
            note=item.get("note", ""),
            marked_by_id=item.get("marked_by"),
        )
        for row in rows
        for item in (row.attendance or [])
    ]
    if presence:
        Attendance.objects.bulk_create(presence, ignore_conflicts=True)

    tied = 0
    for row in rows:
        if row.works:
            tied += Work.objects.filter(pk__in=row.works, slot__isnull=True).update(
                slot_id=row.slot_id
            )

    return {"attendance": len(presence), "works": tied}


@transaction.atomic
def restore_batch(batch) -> dict:
    """
    Отменить действие целиком — все курсы, которых оно коснулось.

    Копирование в школьном виде и массовая уборка идут по нескольким
    курсам, и снимки у них лежат под одной партией. Вернуть один курс из
    трёх значит оставить расписание в состоянии, которого не было никогда.
    """
    totals = {"restored": 0, "created": 0, "deleted": 0, "changed": 0, "courses": 0}

    for snapshot in SlotSnapshot.objects.filter(batch=batch):
        counts = restore(snapshot)
        totals["courses"] += 1
        for key, value in counts.items():
            totals[key] += value

    return totals


def last_for(course):
    """
    Чем можно отменить — самый свежий снимок курса.

    Возвращается сам снимок, а не флаг: кнопка обязана назвать действие
    («Отменить: перенос занятия»), а безымянная отмена страшнее, чем
    полезна — по ней не поймёшь, что вернётся.
    """
    return SlotSnapshot.objects.filter(course=course).first()
