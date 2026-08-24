"""
Фотографии работы и разметка на них: кто их кладёт, кто размечает, кто видит.

Ученик фотографирует тетрадь и присылает снимок — по задаче или на всю работу
разом. Учитель открывает снимок, обводит на нём ошибку, прикалывает к месту
заметку и разговаривает о ней с учеником. Всё это про одну и ту же вещь —
**изображение работы ученика**, — поэтому и живёт одним модулем.

Четыре решения, на которых он стоит.

**Фотография — не отправка.** Соблазн сделать её ответом велик: снимок решения
и есть решение. Но отправка расходует попытку, а попытки считаются по задаче
(«Попытка расходуется на любой отправке»), и тогда ученик, приславший три
снимка одной задачи, потратил бы три попытки из трёх — за одно и то же
решение. Хуже того, у работы без ячеек снимку не на чем было бы висеть вовсе.
Поэтому снимок — материал: он лежит на работе ученика рядом со сканом от
учителя и попыток не трогает.

**Окно решает, ячейка — нет.** Принимается снимок ровно тогда, когда открыто
окно и ученик в курсе, то есть по тем же двум условиям, что и ответ. А вот
`open_for_answers` тут не спрашивается, и это не пропуск: закрытая ячейка
значит «решайте на листе», и фотография листа — ровно то, чем такую ячейку и
сдают. Спроси мы её, единственный законный способ сдать закрытый вопрос
оказался бы закрыт.

**Родитель кладёт снимок за ребёнка.** Отвечать за него он по-прежнему не
может (`IsStudent` у отправки, и это правило остаётся), а сфотографировать
тетрадь — может: ученик младших классов телефона в руках не держит, и
требовать, чтобы снимок пришёл именно от него, значит не дать этой
возможности вовсе. Кто прислал, при этом записано (`Attachment.added_by`) и
видно — «прислала мама» и «прислал Петя» это разные события.

**Разметка хранится мазками, а не переделанной картинкой.** См. `PhotoStroke`:
то же решение, что у Markdown в содержании урока, — отрисовка по дороге на
экран, а не по дороге в базу.
"""

from config.errors import Codes, api_denied, api_error
from django.db import transaction
from django.db.models import Count

from files.models import KIND_FILE, Attachment
from files.services import (
    VIEWER_EXTENSIONS,
    extension_of,
    opens_in_viewer,
    shows_in_text,
)

from .models import CLOSED, Message, PhotoNote, PhotoStroke, StudentWork, Task

# Сколько снимков принимается на одно место — задачу или работу целиком.
#
# Потолок здесь не про диск (за ним следит квота школы), а про просмотр:
# лента из полусотни снимков одного вопроса не листается, а число, которого
# нет вовсе, однажды окажется именно таким.
MAX_PHOTOS = 20

# Толщина пера в тысячных ширины картинки. Нижняя граница — чтобы мазок
# был виден, верхняя — чтобы им нельзя было закрасить работу целиком.
MIN_PEN, MAX_PEN = 1, 60

# Сколько точек принимается в одном мазке. Длинная линия, нарисованная
# медленно, — это несколько сотен точек; десять тысяч это уже не мазок.
MAX_POINTS = 4000

# Самая дальняя страница, на которую кладут пометку. Число это не про PDF — в
# нём страниц бывает и больше, — а про поле в базе: `PositiveSmallIntegerField`
# держит до 32767, и мазок с номером в миллион уронил бы запись ошибкой базы
# вместо честного отказа. Тетрадь на тысячу страниц в школу не сдают.
MAX_PAGE = 999


# --- кто на что имеет право --------------------------------------------------


def teaches(user, work) -> bool:
    """Ведёт ли этот человек курс работы (или чинит его как администратор)."""
    from schedule.models import Course

    return Course.objects.writable_by(user).filter(pk=work.course_id).exists()


def may_draw(user, attachment) -> bool:
    """
    Размечает **учитель**, и только он.

    Разметка — это проверка: обведённая ошибка и приколотая заметка суть
    слова учителя о работе. Дай их ученику — и «исправлено красным» перестало
    бы что-либо значить, потому что красное мог нарисовать и он сам.

    Разговаривать в заметке при этом может и он: см. `may_say`.
    """
    row = attachment.student_work
    if row is None:
        return False
    return teaches(user, row.work)


def may_say(user, attachment) -> bool:
    """
    Пишет в заметку тот, кого она касается: учитель, ученик и его родитель.

    Право по **участию**, а не по виду, — то же правило, что у разговора о
    задаче (`works.threads`): заметка «здесь потерян минус» без ответа «а
    почему?» была бы объявлением, а просили обсуждения.
    """
    from files.access import can_read

    return can_read(user, attachment)


def may_remove(user, attachment) -> None:
    """
    Молчит или отказывает: снять снимок.

    Учитель снимает что угодно со своих курсов — он отвечает за содержимое
    работы. Семья снимает **своё и вовремя**: свой снимок, пока окно
    открыто. После закрытия это уже правка сданного, а не «передумал», и
    разрешать её значило бы дать способ забрать работу после срока.

    Учительский скан семья не трогает никогда, даже свой собственный по
    названию: это запись о работе, а не слова о ней.
    """
    row = attachment.student_work
    if row is None:
        api_denied(
            Codes.ATTACHMENT_FORBIDDEN,
            "This attachment does not belong to a student's work.",
        )

    if teaches(user, row.work):
        return

    from files.access import watched_students

    if row.student_id not in {person.pk for person in watched_students(user)}:
        api_denied(
            Codes.ATTACHMENT_FORBIDDEN,
            "This photo belongs to somebody else's work.",
        )

    if attachment.added_by_id != user.pk:
        api_denied(
            Codes.ATTACHMENT_FORBIDDEN,
            "This was not added by you.",
        )

    if row.work.state() == CLOSED:
        api_error(
            Codes.WORK_CLOSED,
            "This work is closed: what was handed in stays as it is.",
        )


# --- приём снимка ------------------------------------------------------------


def accept(work, student, *, upload, task_id=None, by, now=None) -> Attachment:
    """
    Принять фотографию: одна загрузка — одна ссылка на работе ученика.

    Порядок проверок здесь важен и стоит от дешёвых к дорогим: сперва можно
    ли вообще (окно и зачисление), потом куда (задача этой работы), и только
    потом байты в бакет. Наоборот — значило бы платить за загрузку файла,
    который всё равно отвергнут.
    """
    from files import services as file_services
    from files import storage

    from . import services

    services.may_answer(work, student, now=now)

    task = None
    if task_id is not None:
        # «задача не этой работы» — то же самое, что несуществующая: адрес
        # внутри чужой работы ничего не должен рассказывать о чужой работе
        task = Task.objects.filter(work=work, pk=task_id).first()
        if task is None:
            api_error(
                Codes.TASK_QUESTION_REQUIRED,
                "No such question in this work.",
                field="task",
            )

    if not opens_in_viewer(upload.name):
        # Список — это ровно то, что просмотрщик умеет открыть и разметить.
        # Пока в нём были одни картинки, PDF отказывали справедливо: мы
        # обещали бы страницу, которую он не нарисует. Теперь рисует, и
        # телефонный сканер, отдающий тетрадь PDF'ом, перестал быть тупиком.
        api_error(
            Codes.PHOTO_TYPE_NOT_ALLOWED,
            "A photo or a PDF is expected.",
            field="file",
            allowed=sorted(VIEWER_EXTENSIONS),
        )

    row, _ = StudentWork.objects.get_or_create(work=work, student=student)

    taken = Attachment.objects.filter(student_work=row, task=task).count()
    if taken >= MAX_PHOTOS:
        api_error(
            Codes.TOO_MANY_PHOTOS,
            f"There are already {MAX_PHOTOS} photos here.",
            field="file",
            limit=MAX_PHOTOS,
        )

    try:
        stored, _ = file_services.store_upload(
            upload=upload, school=work.course.school, user=by
        )
    except file_services.UploadRefused as refused:
        api_error(refused.code, refused.detail, field="file", **refused.params)
    except storage.StorageUnavailable:
        api_error(
            Codes.STORAGE_UNAVAILABLE,
            "The file store is not answering. The photo was not saved.",
            field="file",
        )

    return Attachment.objects.create(
        student_work=row,
        task=task,
        kind=KIND_FILE,
        stored_file=stored,
        added_by=by,
        title=upload.name[:200],
        position=taken,
    )


# --- разметка ----------------------------------------------------------------


def rotate(attachment, *, degrees: int) -> Attachment:
    """Повернуть снимок. Мазки не трогаются — они живут в осях исходника."""
    if degrees not in (0, 90, 180, 270):
        api_error(
            Codes.ROTATION_INVALID,
            "Rotation is one of 0, 90, 180, 270.",
            field="rotation",
        )

    attachment.rotation = degrees
    attachment.save(update_fields=["rotation"])
    return attachment


def draw(
    attachment, *, author, color: str, width: int, points, page: int = 0
) -> PhotoStroke:
    """
    Положить мазок поверх снимка — на ту страницу, которую человек видел.

    У снимка страница всегда нулевая, у PDF — та, что открыта. Число сюда
    приходит от клиента и не сверяется с числом страниц в файле: сервер его
    не знает, а узнать значило бы скачать файл из бакета на каждый мазок.
    Цена ошибки при этом никакая — пометка на странице, которой нет, просто
    не покажется, — а цена проверки: гигабайты через два воркера.
    """
    if not isinstance(points, list) or len(points) < 1:
        api_error(Codes.STROKE_EMPTY, "A stroke has no points.", field="points")
    if len(points) > MAX_POINTS:
        api_error(
            Codes.STROKE_TOO_LONG,
            f"A stroke carries at most {MAX_POINTS} points.",
            field="points",
            limit=MAX_POINTS,
        )

    cleaned = [_point(pair, field="points") for pair in points]

    if not (MIN_PEN <= width <= MAX_PEN):
        api_error(
            Codes.PEN_WIDTH_INVALID,
            f"The pen is between {MIN_PEN} and {MAX_PEN}.",
            field="width",
            low=MIN_PEN,
            high=MAX_PEN,
        )

    return PhotoStroke.objects.create(
        attachment=attachment,
        author=author,
        color=_colour(color),
        width=width,
        points=cleaned,
        page=_page(page),
    )


def undo(attachment, *, author, page: int = 0) -> bool:
    """
    Снять последний мазок **на этой странице**. `False` — снимать было нечего.

    Отмена ходит на сервер, а не живёт в памяти вкладки, потому что и сам
    мазок ложится на сервер сразу: вкладку закроют, а вложение, ждущее
    кнопки «сохранить», — это правка, которая тихо не случилась. Цена
    названа честно: отменяется **свой** последний мазок, а не чужой, — иначе
    двое проверяющих одну работу стирали бы друг за другом.

    Страница здесь по той же причине, что и автор. Человек смотрит на седьмую
    страницу и нажимает «отменить»; сними мы мазок с третьей — на экране не
    произойдёт ничего, а работа пропадёт. Нажмут ещё раз.
    """
    last = (
        attachment.strokes.filter(author=author, page=_page(page))
        .order_by("created_at", "id")
        .last()
    )
    if last is None:
        return False

    last.delete()
    return True


def pin(
    attachment, *, author, x: float, y: float, text: str, page: int = 0
) -> PhotoNote:
    """
    Приколоть заметку к месту и сказать в ней первое слово.

    Булавка и первая реплика заводятся вместе одной транзакцией: булавка без
    слов — точка на картинке, которую некому объяснить, и оставлять такую в
    базе значило бы показывать ученику пустой кружок.
    """
    text = (text or "").strip()
    if not text:
        api_error(Codes.MESSAGE_EMPTY, "There is nothing to send.", field="text")

    x, y = _point([x, y], field="x")

    with transaction.atomic():
        note = PhotoNote.objects.create(
            attachment=attachment, author=author, x=x, y=y, page=_page(page)
        )
        Message.objects.create(note=note, author=author, text=text)

    return note


def say(note, *, author, text: str) -> Message:
    """Ответить в заметке. Пустая реплика — не реплика, как и в треде."""
    text = (text or "").strip()
    if not text:
        api_error(Codes.MESSAGE_EMPTY, "There is nothing to send.", field="text")

    message = Message.objects.create(note=note, author=author, text=text)
    # у заметки своя отметка времени: по ней она всплывает в списке, а
    # `auto_now` тут не сработает — правится не она, а её сообщение
    note.save(update_fields=["updated_at"])
    return message


# --- как это выглядит в ответе -----------------------------------------------


def markup_payload(attachment, *, user) -> dict:
    """
    Всё, что нужно нарисовать поверх снимка, одним ответом.

    Одним, а не тремя: просмотрщик открывается по клику и обязан показать
    картинку с пометками сразу, а три запроса подряд дали бы три состояния
    полурисунка — сперва голое фото, потом линии, потом булавки.
    """
    return {
        "id": attachment.pk,
        "title": attachment.title,
        "rotation": attachment.rotation,
        "task": attachment.task_id,
        "added_by": attachment.added_by_id,
        "can_draw": may_draw(user, attachment),
        "strokes": [
            {
                "id": stroke.pk,
                "author": stroke.author_id,
                "color": stroke.color,
                "width": stroke.width,
                # страница едет с каждым мазком, а фильтрует их экран: разметка
                # приезжает **одним** ответом, и делить её на страницы значило
                # бы спрашивать сервер при каждом листании — то есть заново
                # платить за то, что уже привезли
                "page": stroke.page,
                "points": stroke.points,
            }
            for stroke in attachment.strokes.all()
        ],
        "notes": [note_payload(note) for note in attachment.notes.all()],
    }


def note_payload(note) -> dict:
    return {
        "id": note.pk,
        "page": note.page,
        "x": note.x,
        "y": note.y,
        "author": note.author_id,
        "messages": [
            {
                "id": message.pk,
                "author": message.author_id,
                "author_name": (message.author and message.author.get_full_name())
                or "",
                "text": message.text,
                "at": message.created_at,
            }
            for message in note.messages.select_related("author")
        ],
    }


def photo_payload(attachment, *, viewer=None) -> dict:
    """
    Одна фотография в ленте: без разметки, но с числом пометок.

    Разметка сюда не едет намеренно — тридцать снимков класса везли бы
    тысячи точек ради превью размером с ноготь. А вот **есть ли** на снимке
    пометки, видно должно быть до открытия: иначе непроверенный снимок
    неотличим от проверенного.
    """
    return {
        "id": attachment.pk,
        "title": attachment.title,
        "task": attachment.task_id,
        "rotation": attachment.rotation,
        "added_by": attachment.added_by_id,
        # положил ли это спрашивающий. Не «моего ли ученика работа»: снять
        # присланное может тот, кто прислал, — прислала мама, значит и
        # передумать может она. Считает это сервер, а не экран: у ученика
        # своего номера под рукой нет, и сравнивать ему было бы нечем
        "mine": bool(viewer is not None and attachment.added_by_id == viewer.pk),
        # настоящее имя файла, а не название ссылки: значок в списке
        # выбирается по расширению, и совпадают они только пока названия
        # никто не правил
        "file_name": (
            attachment.stored_file.original_name if attachment.stored_file_id else None
        ),
        "content_type": (
            attachment.stored_file.content_type if attachment.stored_file_id else None
        ),
        "size": attachment.stored_file.size if attachment.stored_file_id else None,
        "kind": attachment.kind,
        # Два разных вопроса, и разошлись они ровно тогда, когда просмотрщик
        # научился PDF. `image` — можно ли нарисовать это одним тегом `<img>`
        # (миниатюра, лента). `viewable` — можно ли открыть и разметить: сюда
        # добавляется PDF, который тегом не показать, зато можно нарисовать
        # постранично. Решает расширение, а не догадка экрана: на работе
        # ученика вперемешку лежат снимки с телефона и PDF от учителя.
        "image": bool(
            attachment.stored_file_id
            and shows_in_text(attachment.stored_file.original_name)
        ),
        "viewable": bool(
            attachment.stored_file_id
            and opens_in_viewer(attachment.stored_file.original_name)
        ),
        "pdf": bool(
            attachment.stored_file_id
            and extension_of(attachment.stored_file.original_name) == ".pdf"
        ),
        "url": attachment.url,
        # сколько пометок на снимке: аннотация, когда он пришёл из `sheets`,
        # и свой ответ модели, когда его достали поштучно
        "notes": _counted(attachment, "note_count", attachment.notes),
        "strokes": _counted(attachment, "stroke_count", attachment.strokes),
    }


def _counted(attachment, annotation: str, related) -> int:
    """
    Число из аннотации, а иначе спросить.

    Тем же приёмом, что `is_shared` у вложения, и по той же причине: у
    одиночного снимка считать нечего, а у таблицы на тридцать учеников это
    разница между одним запросом и девяноста — при опросе раз в три секунды.
    """
    counted = getattr(attachment, annotation, None)
    return related.count() if counted is None else counted


def sheets(work, *, student=None, viewer=None) -> dict:
    """
    Все снимки работы, разложенные по ученикам и местам внутри работы.

    `{ученик: {"work": [снимок, …], "tasks": {задача: [снимок, …]}}}`.

    **Одним запросом на всю таблицу**, и это не оптимизация ради красоты.
    Таблица проверки опрашивается раз в три секунды, воркеров у прода два, и
    запрос на строку тут превращается в тридцать; вместе со счётчиками
    пометок — в девяносто. Тем же доводом собран одним проходом весь
    остальной журнал таблицы.

    Число пометок считается здесь же, аннотацией: без него проверенная
    тетрадь неотличима от непроверенной, а спрашивать «а есть ли на этом
    снимке обводка» по разу на снимок — те же тридцать запросов с другой
    стороны. `distinct=True` обязателен: два `Count` по разным связям без
    него перемножают строки и врут обоим.

    Отсюда же берётся число снимков в клетке таблицы: два расчёта над одними
    данными расходятся молча — правило то же, что у сводки и у раскладки
    плана.
    """
    rows = (
        Attachment.objects.filter(student_work__work=work)
        .select_related("stored_file", "student_work")
        .annotate(
            note_count=Count("notes", distinct=True),
            stroke_count=Count("strokes", distinct=True),
        )
        .order_by("position", "id")
    )
    if student is not None:
        rows = rows.filter(student_work__student=student)

    grouped = {}
    for item in rows:
        mine = grouped.setdefault(item.student_work.student_id, empty_sheet())
        payload = photo_payload(item, viewer=viewer)
        if item.task_id is None:
            mine["work"].append(payload)
        else:
            mine["tasks"].setdefault(item.task_id, []).append(payload)

    return grouped


def empty_sheet() -> dict:
    """У кого ничего не приложено. Законное состояние, а не пропуск."""
    return {"work": [], "tasks": {}}


def of_student(work, student, *, viewer=None) -> dict:
    """Снимки одного ученика: тот же ответ, суженный до него."""
    return sheets(work, student=student, viewer=viewer).get(
        student.pk if hasattr(student, "pk") else student, empty_sheet()
    )


# --- разбор присланного ------------------------------------------------------


def _point(pair, *, field: str):
    """Точка — пара долей от нуля до единицы. Всё прочее — отказ, не зажим."""
    try:
        x, y = float(pair[0]), float(pair[1])
    except (TypeError, ValueError, IndexError, KeyError):
        api_error(
            Codes.POINT_INVALID,
            "A point is a pair of numbers between 0 and 1.",
            field=field,
        )

    if not (0 <= x <= 1 and 0 <= y <= 1):
        # зажать в границы было бы хуже отказа: мазок молча переехал бы на
        # край картинки, и объяснить ученику, почему пометка не там, было
        # бы нечем
        api_error(
            Codes.POINT_INVALID,
            "A point is a pair of numbers between 0 and 1.",
            field=field,
        )

    return round(x, 5), round(y, 5)


def _page(value) -> int:
    """
    Номер страницы: целое от нуля. Отрицательное и не-число — отказ.

    Верхней границы нет намеренно: сколько в файле страниц, знает браузер, а
    сервер узнал бы это, только скачав файл из бакета — на каждый мазок. См.
    `draw`: цена ошибки тут никакая, цена проверки — гигабайты через два
    воркера.
    """
    try:
        page = int(value)
    except (TypeError, ValueError):
        api_error(Codes.PAGE_INVALID, "A page is a whole number from zero.", field="page")

    if page < 0 or page > MAX_PAGE:
        api_error(Codes.PAGE_INVALID, "A page is a whole number from zero.", field="page")

    return page


def _colour(value: str) -> str:
    """`#rrggbb` и ничего больше: цвет уезжает в `style`, и там ему верят."""
    value = (value or "").strip().lower()
    if len(value) != 7 or value[0] != "#" or any(
        char not in "0123456789abcdef" for char in value[1:]
    ):
        api_error(Codes.COLOUR_INVALID, "A colour is #rrggbb.", field="color")
    return value
