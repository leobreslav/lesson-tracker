"""
Две половины одного экрана: учитель составляет работу, ученик её решает.

Учительская половина — объект курса (`CourseScopedViewSet`), как и учебный
план; у ученической свои вьюхи: спрашивают они другое и отвечают другим, а
общий вьюсет с ветками «если ученик» был бы длиннее двух.
"""

from config.access import (
    CourseScopedViewSet,
    IsSchoolMember,
    IsFamily,
    IsStudent,
    IsTeacher,
)
from config.errors import Codes, api_error
from families.viewing import subject_of
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import assembling, photos, services, statements, threads, track
from .models import Thread
from vision import services as vision_services
from .models import Submission, Task, Work
from .models import Mark
from .serializers import (
    CriteriaSerializer,
    GradeSerializer,
    QuestionsSerializer,
    ReassignSerializer,
    ScanApplySerializer,
    ScanPageSerializer,
    ScanQuestionsSerializer,
    ScanReadSerializer,
    SplitSerializer,
    StudentSubmissionSerializer,
    SubmissionSerializer,
    TaskSerializer,
    WorkSerializer,
    files_of,
    work_files_prefetch,
)


class TaskThreadView(APIView):
    """
    Разговор о задаче: `?task=&student=`.

    Живёт отдельным адресом, а не действием работы, потому что смотрят на него
    с двух сторон: учитель — из проверки, ученик — со своей страницы задачи. И
    тот и другой спрашивают одно и то же.
    """

    permission_classes = [IsAuthenticated]

    def find(self, request):
        from .models import Task

        task = get_object_or_404(Task, pk=request.query_params.get("task"))
        student_id = int(request.query_params.get("student") or request.user.pk)
        threads.refuse_unless_allowed(request.user, task, student_id)
        return task, student_id

    def get(self, request):
        task, student_id = self.find(request)
        thread = Thread.objects.filter(task=task, student_id=student_id).first()
        if thread is None:
            return Response({"messages": [], "task": task.pk, "student": student_id})
        return Response(threads.payload(thread))

    def post(self, request):
        task, student_id = self.find(request)
        threads.say(
            task,
            student_id=student_id,
            author=request.user,
            text=request.data.get("text", ""),
        )
        return Response(threads.payload(Thread.objects.get(task=task, student_id=student_id)))


class WorkViewSet(CourseScopedViewSet):
    """
    Работы курса. Принадлежат курсу, как и план: читает тот, кто в курсе
    работает, правит назначенный ведущий.

    Правку открытой работы никто не запрещает — она отвечает `impact`, и
    интерфейс называет цену числом: «сейчас решают семнадцать человек».
    Запрет здесь дороже ошибки: опечатку в условии находят посреди урока.
    """

    serializer_class = WorkSerializer
    # приложенное к заданию едет вместе с работой: списком его показывает
    # карточка, а окно правки берёт его оттуда же. Выборка готовая — с
    # фильтром и счётом ссылок внутри (`work_files_prefetch`), иначе на
    # каждую работу курса пришёлся бы свой запрос
    queryset = Work.objects.select_related("course")
    course_path = "course"

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .annotate(task_count=Count("tasks"))
            .prefetch_related(work_files_prefetch())
        )

        course = self.request.query_params.get("course")
        if course:
            queryset = (
                queryset.filter(course_id=course)
                if course.isdigit()
                else queryset.none()
            )

        return queryset

    def perform_destroy(self, instance):
        """
        Удаление уносит задачи и ответы: это каскад, и он намеренный.

        Ответы живут внутри работы и вне её не значат ничего — «ответ на
        задачу, которой нет» нельзя ни прочитать, ни оценить. Поэтому цена
        названа заранее: `impact` показывает, сколько ответов исчезнет, и
        интерфейс спрашивает подтверждение.
        """
        instance.delete()

    @action(detail=False, methods=["post"], url_path="from-bank")
    def from_bank(self, request):
        """
        Собрать работу из задач банка.

        Курс называется в теле, а не берётся из объекта: объекта ещё нет.
        Поэтому и проверка своя — `my_courses()`, как у импорта плана: без неё
        любой учитель школы завёл бы работу в чужом курсе.
        """
        course = get_object_or_404(
            self.my_courses(), pk=request.data.get("course") or 0
        )
        slot = None
        if request.data.get("slot"):
            from schedule.models import Slot

            slot = get_object_or_404(
                Slot.objects.filter(course=course), pk=request.data["slot"]
            )

        work = assembling.assemble(
            course,
            problems=request.data.get("problems") or [],
            title=request.data.get("title") or "",
            slot=slot,
            is_homework=bool(request.data.get("is_homework")),
            user=request.user,
        )
        return Response(
            WorkSerializer(work, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="add-from-bank")
    def add_from_bank(self, request, pk=None):
        """Дописать задачи банка в конец готовой работы."""
        work = self.get_object()
        made = assembling.add(
            work, problems=request.data.get("problems") or [], user=request.user
        )
        return Response({"added": len(made)}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def impact(self, request, pk=None):
        """Что стоит за этой работой прямо сейчас — до того, как её правят."""
        work = self.get_object()

        return Response(services.impact_of(work))

    @action(detail=True, methods=["get", "put"])
    def criteria(self, request, pk=None):
        """
        Шкала работы: список критериев целиком, как строки шаблона.

        Целиком, а не по одному, потому что порядок хранится позицией, и при
        записи набором он равен индексу — ни дыры, ни дубля возникнуть не
        может. Пустой список значит «не оценивается»: отдельного флага нет,
        оценивание **и есть** наличие критериев.

        Правка шкалы у работы, где уже стоят оценки, не запрещается — как и
        правка условия, — но называет цену: сколько оценок исчезнет вместе с
        убранными критериями.
        """
        work = self.get_object()

        if request.method == "GET":
            return Response(services.scale_payload(work))

        form = CriteriaSerializer(data=request.data)
        form.is_valid(raise_exception=True)

        services.set_scale(work, form.validated_data["criteria"])
        return Response(services.scale_payload(work))

    @action(detail=True, methods=["get"])
    def scale_impact(self, request, pk=None):
        """Сколько оценок потеряет правка шкалы: цена называется заранее."""
        work = self.get_object()

        return Response(
            {
                "marks": Mark.objects.filter(student_work__work=work).count(),
                "students": work.students.filter(marks__isnull=False)
                .distinct()
                .count(),
            }
        )

    @action(detail=True, methods=["post"])
    def grade(self, request, pk=None):
        """
        Поставить оценку одному ученику: весь набор критериев за раз.

        По одному критерию не пишем: у MYP их четыре, и ставятся они за один
        взгляд на работу. Комментарий — там же, и он бывает без оценки:
        работа может не оцениваться вовсе, а сказать о ней есть что.
        """
        work = self.get_object()
        form = GradeSerializer(data=request.data, context={"work": work})
        form.is_valid(raise_exception=True)
        data = form.validated_data

        row = services.grade(
            work,
            data["student"],
            marks=data.get("marks"),
            scores=data.get("scores"),
            comment=data.get("comment"),
            final=data.get("final"),
            by=request.user,
        )

        return Response(
            {
                "id": row.pk,
                "student": row.student_id,
                "comment": row.comment,
                "marks": services.marks_of(row),
                "scores": services.scores_of(row),
                # итог после правки: выведенное системой могло измениться
                # вместе с баллами, и пересчитывать его в браузере значило бы
                # завести второй расчёт
                "grade": services.final_grade(work, row),
            }
        )

    @action(detail=True, methods=["post"])
    def split(self, request, pk=None):
        """
        Разложить один скан по ученикам.

        Разметку делает человек, здесь только режут: где чья работа —
        вопрос, на который смотрят глазами, и угадывать его нельзя. Всё
        одной транзакцией: половина разобранной пачки хуже неразобранной,
        потому что непонятно, какая половина.

        Исходник не сохраняется. Он лежит у учителя на диске, а в системе
        был бы одним файлом со всеми работами класса.
        """
        work = self.get_object()
        form = SplitSerializer(data=request.data, context={"work": work})
        form.is_valid(raise_exception=True)

        return Response(
            services.split_scan(
                work,
                data=form.validated_data["data"],
                pieces=form.validated_data["plan"],
                by=request.user,
            )
        )

    @action(detail=True, methods=["get", "put"])
    def questions(self, request, pk=None):
        """
        Вопросы работы целиком: условия, максимумы и эталоны.

        Списком, а не по одному, и по той же причине, что у шкалы: позиция —
        индекс в присланном, и ни дыры, ни дубля возникнуть не может.
        """
        work = self.get_object()

        if request.method == "PUT":
            form = QuestionsSerializer(data=request.data)
            form.is_valid(raise_exception=True)
            services.set_questions(
            work, form.validated_data["questions"], by=request.user
        )

        return Response(
            {
                "questions": [
                    {
                        "id": task.pk,
                        "position": task.position,
                        # имя вопроса и то, что его задаёт: экран показывает
                        # `name`, а правит `label` — пустое значит «зовусь
                        # номером по порядку»
                        "label": task.label,
                        "name": task.name,
                        "question": statements.statement_of(task),
                        "shown": statements.shown(task),
                        "maximum": task.maximum,
                        "answers": statements.answers_of(task),
                    }
                    for task in work.tasks.all()
                ]
            }
        )

    @action(detail=True, methods=["post"], url_path="scan/read")
    def scan_read(self, request, pk=None):
        """
        Прочитать шапку одной страницы. Одна страница — один запрос.

        Цикл ведёт браузер, и это не мелочь оформления: у него уже отрисованы
        страницы, каждый запрос живёт секунду-другую, воркер между ними
        свободен, прогресс виден сам собой, а неудачная страница повторяется
        по одной. Пачка целиком, отданная серверу, заняла бы половину прода на
        минуты — при двух воркерах это отказ в обслуживании себе самому.

        Прочитанное ложится в базу: чтение стоит денег, и вторая попытка за ту
        же страницу не должна платить снова.
        """
        work = self.get_object()

        form = ScanReadSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        index = form.validated_data["index"]
        fingerprint = form.validated_data.get("fingerprint") or ""

        known = work.scan_pages.filter(index=index).first()
        if known and fingerprint and known.fingerprint == fingerprint:
            return Response(services.scan_state(work) | {"cached": True})

        data = vision_services.read_and_charge(
            school=work.course.school,
            user=request.user,
            work=work,
            image=form.validated_data["strip"].read(),
            plain=(
                form.validated_data["plain"].read()
                if form.validated_data.get("plain")
                else None
            ),
            candidates=[person.full for person in services.scan_roster(work)],
            reader=form.validated_data["reader"],
            second=form.validated_data["second"],
        )

        services.save_scan_reading(
            work, index=index, fingerprint=fingerprint, data=data
        )
        return Response(services.scan_state(work) | {"cached": False})

    @action(detail=True, methods=["get", "delete"], url_path="scan/state")
    def scan_state(self, request, pk=None):
        """Что уже прочитано и как оно разложилось. DELETE — начать пачку заново."""
        work = self.get_object()
        if request.method == "DELETE":
            work.scan_pages.all().delete()
        return Response(services.scan_state(work))

    @action(detail=True, methods=["post"], url_path="scan/page")
    def scan_page(self, request, pk=None):
        """
        Поправить страницу руками: чья она и что в клетках.

        Решение человека помечается и автоматической раскладкой больше не
        пересматривается — она предлагает, он решает. Тем же путём приходит и
        «шапки тут нет»: читать такую страницу незачем, а знать о ней надо —
        ряд безшапочных листов размечает пачку.
        """
        work = self.get_object()

        form = ScanPageSerializer(data=request.data, context={"work": work})
        form.is_valid(raise_exception=True)
        fields = dict(form.validated_data)
        ours = fields.pop("ours", False)
        if fields.pop("headerless", False):
            services.mark_headerless(work, index=fields["index"], ours=ours)
        else:
            services.edit_scan_page(work, **fields)
        return Response(services.scan_state(work))

    @action(detail=True, methods=["post"], url_path="scan/questions")
    def scan_questions(self, request, pk=None):
        """
        Прочитать лист условий и записать задачи в шкалу.

        По флагу, а не всегда: страница условий стоит заметно дороже полоски
        шапки — она читается целиком и моделью посерьёзнее, потому что это
        транскрипция формул. Зато и читается она **один раз на пачку**: условия
        раздают одинаковые, и второй экземпляр ничего нового не скажет.
        """
        work = self.get_object()

        form = ScanQuestionsSerializer(data=request.data)
        form.is_valid(raise_exception=True)

        found = vision_services.questions_and_charge(
            school=work.course.school,
            user=request.user,
            work=work,
            image=form.validated_data["sheet"].read(),
        )
        return Response(services.apply_questions(work, by=request.user, found=found))

    @action(detail=True, methods=["post"], url_path="scan/apply")
    def scan_apply(self, request, pk=None):
        """
        Применить разобранную пачку: страницы ученикам, баллы в оценки.

        Файл присылается второй раз — резать-то нечего: исходник мы не храним,
        и это решение, а не забывчивость. У браузера он всё ещё в руках, так
        что второй отправки это стоит ровно ничего.
        """
        work = self.get_object()

        form = ScanApplySerializer(data=request.data)
        form.is_valid(raise_exception=True)
        upload = form.validated_data["file"]
        return Response(
            services.scan_apply(
                work,
                data=upload.read(),
                # имя файла едет вместе с байтами: пачка остаётся у работы, и
                # узнаётся она человеком по тому имени, под которым он её и
                # сканировал
                name=upload.name,
                by=request.user,
            )
        )

    @action(detail=True, methods=["post"])
    def reassign(self, request, pk=None):
        """
        Переложить чужую работу тому, чья она.

        Ошибка в разборе — это чужая контрольная у одноклассника, и
        исправляться она должна одним движением: иначе её будут исправлять
        «потом». Исходника у нас нет, поэтому переносится сама страница —
        вложение меняет владельца, а файл в бакете остаётся тот же.
        """
        work = self.get_object()
        form = ReassignSerializer(data=request.data, context={"work": work})
        form.is_valid(raise_exception=True)

        return Response(
            services.reassign_paper(
                work,
                attachment=form.validated_data["attachment"],
                student=form.validated_data["student"],
            )
        )

    # имя метода не `photos`: модуль `works.photos` зовут отсюда же, и
    # одноимённый атрибут класса читался бы как он, стоило бы кому-нибудь
    # обратиться к нему через `self`
    @action(detail=True, methods=["get"], url_path="photos")
    def student_photos(self, request, pk=None):
        """
        Снимки одного ученика по этой работе: по работе целиком и по задачам.

        Одним ответом на обе раскладки, а не двумя адресами, и это про
        просмотрщик: листают в нём **внутри** набора — снимки этой задачи
        или снимки всей работы, — и какой из наборов открыт, решает то, куда
        нажали. Раздельные адреса означали бы второй запрос ровно в тот
        момент, когда человек нажал «дальше».

        Ученик называется параметром: работа общая, а тетрадь — его.
        """
        work = self.get_object()

        raw = request.query_params.get("student")
        if not (raw or "").isdigit():
            api_error(
                Codes.SPLIT_NOT_IN_COURSE,
                "Say whose photos these are.",
                field="student",
            )

        mine = photos.sheets(work, viewer=request.user).get(
            int(raw), photos.empty_sheet()
        )

        return Response(
            {
                "work": mine["work"],
                "tasks": [
                    {
                        "id": task.pk,
                        "name": task.name,
                        "photos": mine["tasks"].get(task.pk, []),
                    }
                    for task in work.tasks.all()
                ],
            }
        )

    @action(detail=True, methods=["get"])
    def table(self, request, pk=None):
        """
        Сводная таблица: ученики по строкам, задачи по столбцам.

        `?version=` делает опрос дешёвым. Экран спрашивает раз в несколько
        секунд, воркеров у прода два, и ответ «ничего не изменилось» обязан
        стоить один агрегат, а не сборку трёхсот ячеек. Совпала версия —
        отвечаем `changed: false` и больше ничем.
        """
        work = self.get_object()
        version = services.table_version(work)

        if request.query_params.get("version") == version:
            return Response({"version": version, "changed": False})

        return Response(services.build_table(work))


class StudentTrackView(APIView):
    """
    След ученика: что он решал за всё время, собранный по **условиям**.

    Учителю показываются только его курсы: «в 9Б он решал это в марте» —
    сведение о чужом курсе, а след общий на всю школу. Ученик спрашивает свой
    и видит его целиком; чужой ему не показывается вовсе — 404, как везде.

    Ради этого следа ячейка и держит ссылку на условие, а не копию текста:
    задача, спрошенная в пятом классе и в девятом, остаётся тем же объектом, и
    сложить эти встречи можно только так.
    """

    permission_classes = [IsAuthenticated, IsSchoolMember]

    def get(self, request, student):
        from accounts.models import User
        from schedule.models import Course

        me = request.user
        if me.kind == "student":
            if me.pk != int(student):
                raise Http404
            rows = track.track(me)
        else:
            person = get_object_or_404(User.objects.filter(school=me.school), pk=student)
            rows = track.track(person, courses=Course.objects.for_teacher(me))

        return Response({"track": rows, "summary": track.summary(rows)})


class TaskViewSet(CourseScopedViewSet):
    """
    Задачи внутри работы. Курс тот же, путь до него — через работу.

    Позиции плотные, как в плане: новая встаёт в конец, `move` двигает на
    шаг, удаление перенумеровывает уровень.
    """

    serializer_class = TaskSerializer
    queryset = Task.objects.select_related("work")
    course_path = "work__course"

    def get_queryset(self):
        queryset = super().get_queryset()

        work = self.request.query_params.get("work")
        if work:
            queryset = (
                queryset.filter(work_id=work) if work.isdigit() else queryset.none()
            )

        return queryset

    def perform_create(self, serializer):
        work = serializer.validated_data["work"]
        serializer.save(position=services.next_position(work))

    def perform_destroy(self, instance):
        work = instance.work
        instance.delete()
        services.reindex(work)

    @action(detail=True, methods=["post"])
    def take(self, request, pk=None):
        """
        Взять в эту ячейку условие из банка — или снять его совсем.

        Не то же самое, что дописать задачи в конец работы: здесь названо
        **место**. Поленились искать и собрали работу пустыми ячейками — потом
        заполняете третью, не трогая остальные.
        """
        from bank.models import Problem

        task = self.get_object()
        wanted = request.data.get("problem")
        problem = (
            get_object_or_404(Problem.objects.visible_to(request.user), pk=wanted)
            if wanted
            else None
        )
        statements.take(task, problem, user=request.user)
        task.refresh_from_db()
        return Response(
            TaskSerializer(task, context=self.get_serializer_context()).data
        )

    @action(detail=True, methods=["post"])
    def move(self, request, pk=None):
        """`{"direction": "up"|"down"}`; `{"moved": false}` — край, не ошибка."""
        task = self.get_object()
        direction = request.data.get("direction")
        if direction not in ("up", "down"):
            api_error(
                Codes.MODE_INVALID,
                "Direction must be «up» or «down».",
                field="direction",
            )

        return Response({"moved": services.move(task, direction)})

    @action(detail=True, methods=["get"])
    def impact(self, request, pk=None):
        """Сколько ответов и вердиктов затронет правка этой задачи."""
        return Response(services.task_impact(self.get_object(), user=request.user))

    @action(detail=True, methods=["post"])
    def recheck(self, request, pk=None):
        """
        Снять отметки со всех отправок задачи.

        Главный случай — неверный эталон: половина класса проверена
        неправильно, и вердикты надо вернуть в «не проверено», не трогая
        сами ответы.
        """
        return Response({"reset": services.reset_verdicts(self.get_object())})


class SubmissionViewSet(CourseScopedViewSet):
    """
    Отправки учеников: читать и отмечать. Больше ничего.

    Ни создать, ни удалить: журнал пишет ученик, и строка в нём — событие,
    а не запись, которую правят. Учителю принадлежит **отметка**, и она
    здесь единственное изменяемое поле.

    Проверяют чаще по задачам, чем по ученикам: открыть столбец и пройти
    все ответы подряд — глаз настроен на один эталон. Поэтому список
    сужается и по задаче, и по ученику, а ячейка таблицы — это тот же
    список из одной пары.
    """

    serializer_class = SubmissionSerializer
    queryset = Submission.objects.select_related("student", "task")
    course_path = "task__work__course"
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        queryset = super().get_queryset()

        for param, lookup in (
            ("task", "task_id"),
            ("student", "student_id"),
            ("work", "task__work_id"),
        ):
            raw = self.request.query_params.get(param)
            if raw:
                queryset = (
                    queryset.filter(**{lookup: raw})
                    if raw.isdigit()
                    else queryset.none()
                )

        return queryset.order_by("created_at", "id")

    def perform_update(self, serializer):
        """
        Балл ставится и снимается одним и тем же PATCH.

        `null` — «снять»: учитель передумал или увидел, что смотрел не ту
        отправку. Попытку это не расходует и ответ ученика не трогает: он
        неизменен по определению.

        Сама отправка при этом не правится вовсе — меняется оценка на паре
        «ученик и вопрос», а сюда PATCH приходит потому, что проверяют
        **этот** ответ. `services.check_answer` и связывает одно с другим.
        """
        services.check_answer(
            serializer.instance,
            value=serializer.validated_data.get("mark"),
            by=self.request.user,
        )


# --- половина ученика --------------------------------------------------------------


class StudentWorksView(APIView):
    """
    Работы ученика: открытые, закрытые и его продвижение по ним.

    Ненаступивших здесь нет вовсе — «черновика» у работы нет, и до открытия
    окна её не существует. Закрытые остаются: ответы и отметки читать можно
    всегда.
    """

    # Родитель видит тот же список про своего ребёнка. Отправлять ответы он
    # при этом не может — это другая вьюха и другое право (`IsStudent`):
    # смотреть за учёбой и учиться вместо ребёнка — разные вещи.
    permission_classes = [IsAuthenticated, IsSchoolMember, IsFamily]

    def get(self, request):
        student = subject_of(request)
        works = list(services.visible_works(student))
        totals = services.totals_for(works, student=student)
        active = set(
            student.enrolments.filter(removed_at__isnull=True).values_list(
                "course_id", flat=True
            )
        )

        return Response(
            {
                "works": [
                    {
                        "id": work.pk,
                        "title": work.title,
                        "course_id": work.course_id,
                        "course_name": work.course.name,
                        "state": work.state(),
                        "opens_at": work.opens_at,
                        "closes_at": work.closes_at,
                        # снятый с курса видит работу и свои ответы, но
                        # решать в ней больше не может. Второе условие — про
                        # сами вопросы: работа, все ячейки которой пишутся на
                        # бумаге, открыта и доступна, а отвечать в ней негде
                        "can_answer": work.state() == "open"
                        and work.course_id in active
                        and totals[work.pk]["open_tasks"] > 0,
                        "tasks": totals[work.pk]["tasks"],
                        "answered": totals[work.pk]["answered_tasks"],
                    }
                    for work in works
                ]
            }
        )


class StudentWorkView(APIView):
    """Одна работа целиком: задачи, свои ответы и что ещё можно отправить."""

    permission_classes = [IsAuthenticated, IsSchoolMember, IsFamily]

    def get(self, request, pk):
        student = subject_of(request)
        work = get_object_or_404(services.visible_works(student), pk=pk)

        # опрос у ученика такой же, как у учителя, и по той же причине:
        # отметка приходит к нему без его участия, а страница, которую
        # приходится обновлять руками, — это страница, которой не верят
        version = services.student_version(work, student)
        if request.query_params.get("version") == version:
            return Response({"version": version, "changed": False})

        tasks = list(work.tasks.all())
        journal = services.my_answers(student, tasks)
        # снимки его работы: по задачам и на работу целиком. Второе едет в
        # `papers` внутри `my_grade` — там же, где скан от учителя, потому
        # что для ученика это одно и то же: изображение его работы
        shots = photos.of_student(work, student, viewer=request.user)["tasks"]
        active = student.enrolments.filter(
            course_id=work.course_id, removed_at__isnull=True
        ).exists()

        return Response(
            {
                "version": version,
                "id": work.pk,
                "title": work.title,
                "description": work.description,
                # Приложенное к заданию: условия pdf'ом, бланк, что угодно.
                # Тем же расчётом, что и у учителя, но **его** составом:
                # спрятанное от класса (ответы, разбор, отсканированная
                # пачка) сюда не едет. Это единственное место, где стороны
                # расходятся, и потому флаг назван прямо, а не подразумевается.
                "files": files_of(work, staff=False),
                "course_name": work.course.name,
                "state": work.state(),
                "opens_at": work.opens_at,
                "closes_at": work.closes_at,
                "attempts": work.attempts,
                # зачислен ли он сейчас — отдельно от «есть ли что отвечать»:
                # экран говорит разное про «вы больше не в курсе» и «эти
                # вопросы пишут на бумаге», и одним флагом их не различить
                "enrolled": active,
                "can_answer": work.state() == "open"
                and active
                and any(task.open_for_answers for task in tasks),
                "tasks": [
                    {
                        "id": task.pk,
                        "position": task.position,
                        # как вопрос назван в работе. Ученику важнее, чем
                        # учителю: он слышит «второй пункт первой задачи» на
                        # уроке и должен найти на экране «1б», а не «2»
                        "name": task.name,
                        # сколько стоит вопрос: без этого числа балл ученику
                        # не объяснить — «2» само по себе не говорит ничего,
                        # а «2 из 3» говорит всё
                        "maximum": task.maximum,
                        # принимает ли этот вопрос ответы. Свойство ячейки, а
                        # не работы: «Q1 и Q2 решайте онлайн, Q3 сдайте на
                        # листе» — обычный случай, невыразимый флагом работы
                        "open_for_answers": task.open_for_answers,
                        "question": statements.statement_of(task),
                        # ученику — с оглядкой на выключенную шапку: если её
                        # спрятали, не приезжает ни она сама, ни пометка,
                        # иначе скрытие бессмысленно
                        "shown": statements.shown(task, to_student=True),
                        # «эту задачу вы уже решали» — факт, но **без
                        # ответа**: старый ответ показывается там, где ему
                        # место, — в той работе, и только если она закрыта.
                        # Иначе повторный вопрос теряет смысл: его задают,
                        # чтобы посмотреть, как человек решает сейчас.
                        "seen_before": track.seen_by(
                            student, task.problem, besides=work
                        )
                        if task.problem_id
                        else [],
                        "attempts_left": services.attempts_left(
                            work, len(journal[task.pk])
                        ),
                        # фотографии, присланные по этой задаче. Их видно
                        # всегда, а не по `show_result`: это его собственная
                        # тетрадь, и прятать её не от кого — то же правило,
                        # что у скана работы
                        "photos": shots.get(task.pk, []),
                        "submissions": StudentSubmissionSerializer(
                            journal[task.pk], many=True, context={"work": work}
                        ).data,
                    }
                    for task in tasks
                ],
                # оценка и слова учителя — по тому же правилу, что вердикт:
                # `show_result` решает, видно ли сразу или после закрытия
                **services.my_grade(work, student, viewer=request.user),
            }
        )


class StudentAnswerView(APIView):
    """
    Отправка ответа: одна задача, одна попытка, новая строка журнала.

    Ответы уходят по одной задаче, а не всё разом в конце: браузер закроют,
    интернет отвалится, урок кончится — и работа, отправляемая целиком, в
    этот момент теряется вся.
    """

    permission_classes = [IsAuthenticated, IsSchoolMember, IsStudent]

    def post(self, request, pk):
        task = get_object_or_404(
            Task.objects.filter(
                work__in=services.visible_works(request.user)
            ).select_related("work"),
            pk=pk,
        )
        text = request.data.get("answer")
        if not isinstance(text, str):
            api_error(Codes.TASK_QUESTION_REQUIRED, "An answer is required.", field="answer")

        submission = services.answer(task, request.user, text)
        used = Submission.objects.filter(task=task, student=request.user).count()

        return Response(
            {
                "submission": StudentSubmissionSerializer(
                    submission, context={"work": task.work}
                ).data,
                "attempts_left": services.attempts_left(task.work, used),
            },
            status=status.HTTP_201_CREATED,
        )
