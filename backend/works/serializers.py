"""Работы и задачи в JSON. Ответы ученика — отдельно, у них другой читатель."""

from config.errors import Codes, api_error
from rest_framework import serializers
from schedule.models import Course

import json

from django.contrib.auth import get_user_model

from .models import (
    MAX_CRITERIA,
    MAX_MARK,
    MAX_SCAN_BYTES,
    GradingSystem,
    Submission,
    Task,
    Work,
)

User = get_user_model()


def teacher_courses(serializer):
    """
    Курсы, в которых спрашивающий вообще может что-то заводить.

    Именно право, а не «мои»: администратор школы чинит её курсы, а
    показывать по умолчанию ему всё равно надо свои (`for_teacher`).
    """
    user = getattr(serializer.context.get("request"), "user", None)
    return Course.objects.writable_by(user)


class TaskSerializer(serializers.ModelSerializer):
    """
    Ячейка работы глазами учителя.

    Условие и эталоны у неё **не свои** — они живут в `bank.Problem`, — но с
    экрана это одно поле ввода, и провод остаётся тем же: `question` и
    `answers` приходят и уходят как обычные поля. Складывает их в условие
    `statements.say`, одно место на все пути записи.

    `mode` — ответ на вопрос «править везде или сделать копию», и нужен он
    только когда по условию уже отвечали. В остальных случаях умолчание
    очевидно, и спрашивать нечего.
    """

    question = serializers.CharField(
        required=False, allow_blank=True, trim_whitespace=False
    )
    # свой список, а не тот, что DRF выводит из ArrayField: тот отвергает
    # пустую строку раньше, чем до неё дойдёт очередь, и `trim_whitespace`
    # у него включён — а эталон, как и ответ, хранится ровно как введён
    answers = serializers.ListField(
        child=serializers.CharField(allow_blank=True, trim_whitespace=False),
        required=False,
    )
    mode = serializers.CharField(required=False, write_only=True)

    def create(self, validated_data):
        said = self._said(validated_data)
        task = super().create(validated_data)
        self._say(task, said)
        return task

    def update(self, instance, validated_data):
        said = self._said(validated_data)
        task = super().update(instance, validated_data)
        self._say(task, said)
        return task

    @staticmethod
    def _said(validated_data):
        return {
            "text": validated_data.pop("question", None),
            "answers": validated_data.pop("answers", None),
            "mode": validated_data.pop("mode", None),
        }

    def _say(self, task, said):
        from . import statements

        if said["text"] is None and said["answers"] is None:
            return
        statements.say(
            task,
            text=said["text"],
            answers=said["answers"],
            user=self.context["request"].user,
            mode=said["mode"],
        )
        task.refresh_from_db()

    def to_representation(self, instance):
        from . import statements

        data = super().to_representation(instance)
        data["question"] = statements.statement_of(instance)
        data["answers"] = statements.answers_of(instance)
        # Показывать пункт без сюжета нельзя: экран берёт готовый разбор, а не
        # склеенный текст — иначе пропадёт и пометка, и разница между тем, что
        # видит учитель и что ученик.
        data["shown"] = statements.shown(instance)
        # Как вопрос зовётся: своё имя или номер по порядку. Считает это
        # модель, а не экран, — иначе правило «пусто значит номер» жило бы в
        # пяти местах клиента и разъехалось бы при первой же правке.
        data["name"] = instance.name
        return data

    class Meta:
        model = Task
        # `problem` только на чтение: происхождение ставит сборка из банка, а
        # не присланное тело. Иначе задачу можно было бы объявить взятой из
        # чужого условия — и «где её спрашивали» начало бы врать.
        fields = (
            "id",
            "work",
            "position",
            "label",
            "question",
            "answers",
            "maximum",
            "mode",
            "problem",
            "show_stem",
            "open_for_answers",
            "created_at",
        )
        read_only_fields = ("id", "position", "problem", "created_at")

    def validate_answers(self, value):
        # пустые строки в списке эталонов — след пустой строки формы, а не
        # ответ «ничего»: пустой ответ выражается пустым списком
        return [answer for answer in value if answer.strip()]

    def get_fields(self):
        fields = super().get_fields()
        fields["work"].queryset = Work.objects.filter(
            course__in=teacher_courses(self)
        )
        return fields


def work_files_prefetch():
    """
    Вложения задания, готовые к показу, — одной выборкой на весь список.

    `prefetch_related("attachments")` сам по себе тут не помогает, и это тот
    случай, когда «оптимизация» есть, а действия у неё нет: `files_of`
    спрашивал `work.attachments.filter(...)`, а **фильтр по связи ходит в
    базу заново** — кэш prefetch отдаёт только `.all()`. То есть на список из
    тридцати работ выходило тридцать запросов при живом prefetch'е.

    Поэтому и фильтр, и `select_related`, и счёт ссылок (для «файл лежит ещё
    где-то») стоят внутри самого `Prefetch`, а `files_of` разбирает уже
    готовое.
    """
    from django.db.models import Count, Prefetch
    from files.models import Attachment

    return Prefetch(
        "attachments",
        queryset=Attachment.objects.filter(inline=False)
        .select_related("stored_file")
        .annotate(reference_count=Count("stored_file__attachments")),
    )


def files_of(work) -> list:
    """
    Что приложено **к заданию**: условия одним pdf'ом, бланк, разбор.

    Одна функция на обе стороны — на список работ учителя и на страницу
    ученика. Порознь они разошлись бы молча в первую же правку: ученик
    увидел бы не то, что приложил учитель, и заметил бы это он, а не мы.

    Картинки, стоящие **в тексте** пояснений, сюда не попадают: ими
    распоряжается текст, и строкой в списке материалов они были бы записью,
    которую нельзя понять, не открыв пояснения. Тот же довод, что у урока.

    Отсев inline идёт **в питоне**, а не выборкой, и это не мелочь: так
    функция одинаково работает и над готовым prefetch'ем (список работ), и
    над одной работой без него (страница ученика). Спроси она базу — prefetch
    списка не значил бы ничего.
    """
    from files.serializers import AttachmentSerializer

    rows = [item for item in work.attachments.all() if not item.inline]
    return AttachmentSerializer(rows, many=True).data


class WorkSerializer(serializers.ModelSerializer):
    """
    Работа глазами учителя.

    `state` отдаётся сервером, а не считается на клиенте: «открыта ли» —
    вопрос о времени, и два ответа на него (у браузера часы свои) означали
    бы работу, которая на экране открыта, а на сервере ещё нет.
    """

    created_by = serializers.HiddenField(default=serializers.CurrentUserDefault())
    course_name = serializers.CharField(source="course.name", read_only=True)
    state = serializers.SerializerMethodField()
    grade = serializers.SerializerMethodField()
    tasks_count = serializers.SerializerMethodField()
    files = serializers.SerializerMethodField()

    class Meta:
        model = Work
        fields = (
            "id",
            "course",
            "course_name",
            "created_by",
            "title",
            "description",
            "opens_at",
            "closes_at",
            "attempts",
            "show_result",
            "is_homework",
            "is_summative",
            "grading_system",
            "grade",
            "slot",
            "state",
            "tasks_count",
            "files",
            "created_at",
        )
        read_only_fields = ("id", "created_at")

    def get_state(self, work) -> str:
        return work.state()

    def get_grade(self, work) -> dict | None:
        """Как называется система, если она выбрана. Сама отметка — у ученика."""
        system = work.grading_system
        return (
            {"id": system.pk, "name": system.name, "kind": system.kind}
            if system
            else None
        )

    def get_files(self, work) -> list:
        return files_of(work)

    def get_tasks_count(self, work) -> int:
        # аннотация вьюсета; у только что созданной работы задач ноль, и это
        # правда, а не отсутствие данных
        return getattr(work, "task_count", 0)

    def validate(self, attrs):
        def value(name):
            return attrs.get(name, getattr(self.instance, name, None))

        if value("closes_at") <= value("opens_at"):
            api_error(
                Codes.WORK_DATES_REVERSED,
                "The work closes before it opens.",
                field="closes_at",
            )

        return attrs

    def get_fields(self):
        fields = super().get_fields()
        fields["course"].queryset = teacher_courses(self)
        # занятие — из своих курсов; поле необязательное
        from schedule.models import Slot

        fields["slot"].queryset = Slot.objects.filter(
            course__in=fields["course"].queryset
        )
        # системы оценивания — только своей школы и только разрешённые: запрет
        # это единственный рычаг администратора над выбором, и обходить его
        # значением в теле запроса нельзя
        school = getattr(self.context["request"].user, "school", None)
        fields["grading_system"].queryset = GradingSystem.objects.filter(
            school=school, is_allowed=True
        )
        return fields


class SubmissionSerializer(serializers.ModelSerializer):
    """
    Отправка глазами учителя: ответ, время и балл за него.

    Из полей меняется один — `mark`. Ответ ученика не правится ни при каких
    обстоятельствах: это его слова, а не наша запись о них.

    Балл лежит не здесь, а на паре «ученик и вопрос» (`Mark`), и сюда
    приезжает потому, что проверка — это действие над **конкретным
    ответом**: учитель смотрит вот этот текст и оценивает вот его. Ссылка на
    отправку у оценки и хранит эту связь.
    """

    student_name = serializers.SerializerMethodField()
    mark = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=MAX_MARK
    )

    class Meta:
        model = Submission
        fields = (
            "id",
            "task",
            "student",
            "student_name",
            "answer",
            "created_at",
            "mark",
            "checked_at",
        )
        read_only_fields = (
            "id",
            "task",
            "student",
            "answer",
            "created_at",
            "checked_at",
        )

    def get_student_name(self, submission) -> str:
        from . import services

        return services.full_name(submission.student)

    def to_representation(self, submission):
        from .models import Mark

        data = super().to_representation(submission)
        mark = Mark.objects.filter(submission=submission).first()
        data["mark"] = mark.value if mark else None
        return data


# --- то же самое, но для ученика --------------------------------------------------


class StudentSubmissionSerializer(serializers.ModelSerializer):
    """Одна отправка в истории ученика. Балл может быть скрыт настройкой."""

    mark = serializers.SerializerMethodField()

    class Meta:
        model = Submission
        fields = ("id", "answer", "created_at", "mark")

    def get_mark(self, submission):
        from . import services

        return services.mark_for(self.context["work"], submission)


class CriterionSerializer(serializers.Serializer):
    """Одна строка шкалы. Имя пустое — обычная отметка, а не критерий."""

    name = serializers.CharField(max_length=100, allow_blank=True, default="")
    maximum = serializers.IntegerField(min_value=1, max_value=MAX_MARK)


class QuestionSerializer(serializers.Serializer):
    """Один вопрос работы: условие, максимум и эталонные ответы."""

    question = serializers.CharField(
        required=False, allow_blank=True, trim_whitespace=False, default=""
    )
    # Своё имя вопроса; пусто — зовётся номером по порядку.
    #
    # Умолчания нарочно нет, в отличие от `maximum`: с `default=""` ключ
    # приезжал бы всегда, и всякий, кто правит вопросы не ради имён, стирал бы
    # их молча. Отсутствие ключа значит «не трогай», пустая строка — «сними
    # имя», и это два разных намерения.
    label = serializers.CharField(
        required=False, allow_blank=True, max_length=16
    )
    maximum = serializers.IntegerField(min_value=1, max_value=MAX_MARK, default=1)
    answers = serializers.ListField(
        child=serializers.CharField(trim_whitespace=False),
        required=False,
        allow_empty=True,
    )
    # «править везде» или «сделать копию» — спрашивается только когда по
    # условию уже отвечали; в остальных случаях умолчание очевидно
    mode = serializers.CharField(required=False, allow_blank=True)


class QuestionsSerializer(serializers.Serializer):
    """
    Вопросы работы целиком. Позиция — индекс в списке, как у шкалы.

    Пустой список законен: у работы может не быть вопросов вовсе — так
    устроено исследование, которое оценивают только по критериям.
    """

    questions = QuestionSerializer(many=True)


class CriteriaSerializer(serializers.Serializer):
    """
    Шкала целиком. Пустой список законен: работа не оценивается.

    Порядок берётся из списка — позиция это индекс, и другого источника у
    неё нет. Тот же приём, что у строк шаблона в библиотеке, и по той же
    причине: построчный CRUD потребовал бы своей перенумерации ради формы,
    у которой вложенности нет.
    """

    criteria = CriterionSerializer(many=True)

    def validate_criteria(self, value):
        if len(value) > MAX_CRITERIA:
            api_error(
                Codes.TOO_MANY_CRITERIA,
                f"A work is graded by at most {MAX_CRITERIA} criteria.",
                field="criteria",
                limit=MAX_CRITERIA,
            )
        return value


class GradeSerializer(serializers.Serializer):
    """
    Оценка одного ученика: наборы по обеим осям плюс комментарий.

    Осей две: `marks` — уровни по критериям оценивания, `scores` — баллы за
    вопросы работы. Значение `null` снимает отметку — тем же движением, что и
    вердикт у отправки. Чужой критерий и чужой вопрос не примем: перепутать их
    легко, а последствие — оценка, поставленная не туда.
    """

    student = serializers.PrimaryKeyRelatedField(queryset=User.objects.none())
    marks = serializers.DictField(
        child=serializers.IntegerField(min_value=0, max_value=MAX_MARK, allow_null=True),
        required=False,
    )
    scores = serializers.DictField(
        child=serializers.IntegerField(min_value=0, max_value=MAX_MARK, allow_null=True),
        required=False,
    )
    comment = serializers.CharField(required=False, allow_blank=True)
    # итог, поставленный руками. Пустая строка снимает его и возвращает
    # работу системе; не прислали поле вовсе — не трогаем
    final = serializers.CharField(
        required=False, allow_blank=True, max_length=40, trim_whitespace=False
    )

    def get_fields(self):
        fields = super().get_fields()
        work = self.context["work"]
        # только ученики этого курса, включая снятых: работа у них была, и
        # оценка за неё тоже
        fields["student"].queryset = User.objects.filter(
            enrolments__course_id=work.course_id
        )
        return fields

    def validate(self, attrs):
        work = self.context["work"]

        for field, rows in (
            ("marks", work.criteria.all()),
            ("scores", work.tasks.all()),
        ):
            known = {item.pk: item for item in rows}
            checked = {}
            for key, value in (attrs.get(field) or {}).items():
                item = known.get(int(key)) if str(key).isdigit() else None
                if item is None:
                    api_error(
                        Codes.CRITERION_UNKNOWN,
                        "That row does not belong to this work.",
                        field=field,
                    )
                if value is not None and value > item.maximum:
                    api_error(
                        Codes.MARK_OUT_OF_RANGE,
                        f"The mark is above the maximum of {item.maximum}.",
                        field=field,
                        maximum=item.maximum,
                    )
                checked[item.pk] = value
            attrs[field] = checked

        return attrs


class PieceSerializer(serializers.Serializer):
    """Один кусок разметки: чья работа и с какой по какую страницу."""

    student = serializers.IntegerField()
    first = serializers.IntegerField(min_value=1)
    last = serializers.IntegerField(min_value=1)


class SplitSerializer(serializers.Serializer):
    """
    Скан и разметка к нему.

    Разметка приезжает строкой JSON, потому что файл идёт multipart'ом, и
    вложенные структуры в такой форме не выражаются. Это единственная
    причина; списком объектов она и остаётся.
    """

    file = serializers.FileField()
    plan = serializers.CharField()

    def validate(self, attrs):
        from . import splitting

        upload = attrs["file"]
        if upload.size > MAX_SCAN_BYTES:
            api_error(
                Codes.FILE_TOO_LARGE,
                f"The scan is larger than {MAX_SCAN_BYTES // 1024 // 1024} MB.",
                field="file",
                limit_mb=MAX_SCAN_BYTES // 1024 // 1024,
            )

        data = upload.read()
        try:
            pages = splitting.read_pages(data)
        except splitting.SplitError as error:
            api_error(Codes.FILE_NOT_PDF, str(error), field="file")

        try:
            rows = json.loads(attrs["plan"])
        except ValueError:
            api_error(Codes.SPLIT_EMPTY, "The markup is not readable.", field="plan")

        form = PieceSerializer(data=rows, many=True)
        form.is_valid(raise_exception=True)
        pieces = [
            splitting.Piece(
                student_id=item["student"], first=item["first"], last=item["last"]
            )
            for item in form.validated_data
        ]

        work = self.context["work"]
        students = set(
            work.course.students.values_list("student_id", flat=True)
        )
        splitting.check_plan(pieces, pages=pages, students=students)

        attrs["data"] = data
        attrs["plan"] = pieces
        return attrs


class ReassignSerializer(serializers.Serializer):
    """Переложить приложенную работу другому ученику того же курса."""

    attachment = serializers.IntegerField()
    student = serializers.PrimaryKeyRelatedField(queryset=User.objects.none())

    def get_fields(self):
        fields = super().get_fields()
        work = self.context["work"]
        fields["student"].queryset = User.objects.filter(
            enrolments__course_id=work.course_id
        )
        return fields

    def validate_attachment(self, value):
        from files.models import Attachment

        work = self.context["work"]
        found = Attachment.objects.filter(
            pk=value, student_work__work=work
        ).first()
        if found is None:
            api_error(
                Codes.SPLIT_NOT_IN_COURSE,
                "That attachment does not belong to this work.",
                field="attachment",
            )
        return found


class ScanReadSerializer(serializers.Serializer):
    """
    Полоска шапки одной страницы.

    Картинку режет и выпрямляет браузер: страницы у него уже отрисованы, а
    сервер, взявшись за то же самое, потребовал бы растеризатор и целую книгу
    по сети вместо полоски в сотню килобайт.
    """

    index = serializers.IntegerField(min_value=0)
    # FileField, а не ImageField: тот требует Pillow, которого в образе нет и
    # незачем — картинку мы не разбираем, а передаём байтами дальше
    strip = serializers.FileField()
    # Отпечаток полоски: та же страница, загруженная снова, не перечитывается.
    fingerprint = serializers.CharField(max_length=64, required=False, allow_blank=True)
    # Кем читать клетки с баллами. Спрашивается **на каждой странице**, потому
    # что цикл ведёт браузер и другого места для этой просьбы нет; решает же
    # человек один раз на пачку, на шаге выбора файла.
    #
    # Три значения, и они разные: имя читателя — «зови этого», `none` — «клетки
    # берёт тот же, кто прочитал имя», пустая строка — «кем умеете». Умолчание
    # пустое: ключи в контуре появляются не сами, и раз школа их поставила,
    # второй читатель нужен; отказ от него — это явное `none`.
    cells = serializers.CharField(required=False, allow_blank=True, default="")
    # Кем читать имя. Пустая строка — «кем умеете»: контур сам возьмёт первого
    # доступного. Незнакомое имя читателя не отказ, а та же пустая строка:
    # клиент мог отстать от сервера на одну выкатку, и ронять из-за этого
    # пачку, за половину которой уже заплачено, — плохой обмен.
    reader = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_reader(self, name):
        from vision import services as vision_services

        return name if name in vision_services.NAME_READERS else ""

    def validate_cells(self, name):
        """Незнакомое имя — то же «кем умеете», по той же причине, что у имени."""
        from vision import services as vision_services

        known = (*vision_services.CELLS_READERS, vision_services.NOBODY)
        return name if name in known else ""

    def validate_strip(self, upload):
        if upload.size > 4 * 1024 * 1024:
            api_error(
                Codes.FILE_TOO_LARGE,
                "The header strip is larger than 4 MB.",
                field="strip",
                limit_mb=4,
            )
        return upload


class ScanPageSerializer(serializers.Serializer):
    """Ручная правка страницы: чья она и что в клетках."""

    index = serializers.IntegerField(min_value=0)
    # шапки на странице не нашлось — обычно это лист условий; читать его
    # незачем, а знать о нём надо: по нему видно границу между работами
    headerless = serializers.BooleanField(required=False)
    # метка в углу нашлась: значит лист наш, даже если шапку не прочитать
    ours = serializers.BooleanField(required=False)
    student = serializers.IntegerField(required=False, allow_null=True)
    cells = serializers.ListField(
        child=serializers.IntegerField(allow_null=True, min_value=0, max_value=99),
        required=False,
        allow_empty=True,
        max_length=16,
    )

    def validate_student(self, value):
        if value is None:
            return None
        work = self.context["work"]
        known = work.course.students.filter(
            student_id=value, removed_at__isnull=True
        ).exists()
        if not known:
            api_error(
                Codes.SPLIT_NOT_IN_COURSE,
                "That student does not study in this course.",
                field="student",
            )
        return value


class ScanQuestionsSerializer(serializers.Serializer):
    """
    Лист условий картинкой.

    Страницу целиком, а не полоску: условия напечатаны по всему листу, и
    вырезать из них нечего.
    """

    sheet = serializers.FileField()

    def validate_sheet(self, upload):
        if upload.size > 4 * 1024 * 1024:
            api_error(
                Codes.FILE_TOO_LARGE,
                "The question sheet is larger than 4 MB.",
                field="sheet",
                limit_mb=4,
            )
        return upload


class ScanApplySerializer(serializers.Serializer):
    """Тот же файл ещё раз — чтобы было что резать."""

    file = serializers.FileField()

    def validate_file(self, upload):
        if upload.size > MAX_SCAN_BYTES:
            api_error(
                Codes.FILE_TOO_LARGE,
                f"The scan is larger than {MAX_SCAN_BYTES // 1024 // 1024} MB.",
                field="file",
                limit_mb=MAX_SCAN_BYTES // 1024 // 1024,
            )
        return upload
