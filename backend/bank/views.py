"""
Банк задач: источники, условия, решения и словарь.

Права тут не по виду пользователя, а по владению: системное правит
суперпользователь, школьное и личное — администратор школы, личное — ещё и
автор. Поэтому вьюхи стоят на `IsTeacher` (ученику банк не показывают вовсе),
а внутри спрашивают `writable_by`.
"""

from config.access import IsSchoolMember, IsTeacher
from config.errors import Codes, api_error
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import copying, expressions, importing, proposals, search, services, topics
from .owning import writable_ids
from .models import (
    NEGATABLE,
    ON_PROBLEM,
    ON_SOLUTION,
    Entry,
    Problem,
    ProblemTag,
    Section,
    Solution,
    SolutionTag,
    Introduction,
    Source,
    Proposal,
    Tag,
    Topic,
)


class BankView(APIView):
    """Общая рамка: банк — учительская часть, ученику его не показывают."""

    permission_classes = [IsAuthenticated, IsSchoolMember, IsTeacher]


class SourcesView(BankView):
    """Полка источников: системные, школьные и свои."""

    def get(self, request):
        sources = Source.objects.visible_to(request.user).prefetch_related("entries")
        subject = request.query_params.get("subject")
        if subject and subject.isdigit():
            sources = sources.filter(subject_id=subject)
        sources = list(sources.select_related("subject"))
        mine = writable_ids(Source, request.user, sources)
        return Response(
            {
                "sources": [
                    {
                        "id": source.pk,
                        "title": source.title,
                        "author": source.author,
                        "level": source.level,
                        "problems": source.entries.count(),
                        "subject": source.subject_id,
                        "subject_name": source.subject.name if source.subject_id else "",
                        "may_edit": source.pk in mine,
                    }
                    for source in sources
                ]
            }
        )

    def post(self, request):
        title = (request.data.get("title") or "").strip()
        if not title:
            api_error(
                Codes.GRADING_NAME_REQUIRED, "A source needs a title.", field="title"
            )

        level = request.data.get("level") or "personal"
        if level == "system" and not request.user.is_superuser:
            api_error(
                Codes.SUPERUSER_REQUIRED,
                "Only a superuser adds to the system catalogue.",
                field="level",
            )
        if level == "school" and not request.user.is_school_admin:
            api_error(
                Codes.SCHOOL_ADMIN_REQUIRED,
                "Only a school administrator adds to the school catalogue.",
                field="level",
            )

        source = Source.objects.create(
            title=title,
            author=(request.data.get("author") or "").strip(),
            subject_id=request.data.get("subject") or None,
            school=None if level == "system" else request.user.school,
            owner=request.user if level == "personal" else None,
            created_by=request.user,
        )
        return Response({"id": source.pk, "title": source.title}, status=201)


class SourceView(BankView):
    """Одна книга: оглавление и задачи раздела."""

    def find(self, request, pk):
        return get_object_or_404(Source.objects.visible_to(request.user), pk=pk)

    def get(self, request, pk):
        source = self.find(request, pk)
        section = request.query_params.get("section")
        label = (request.query_params.get("label") or "").strip()

        entries = source.entries.select_related("problem", "section", "parent")
        if label:
            # Номер — это адрес, а не текст: «14а» ищется точным совпадением.
            # Спросили номер целиком — отдаём его вместе с пунктами: «покажи
            # весь третий» и «покажи 3б» — разные вопросы, и оба законные.
            entries = entries.filter(
                Q(label__iexact=label) | Q(parent__label__iexact=label)
            )
        elif section == "none":
            # «вне разделов» — это выбор, а не отсутствие выбора: задачи,
            # которые в оглавление не разложили, надо уметь увидеть отдельно
            entries = entries.filter(section__isnull=True)
        elif section:
            entries = entries.filter(section_id=section)

        # Без выбора показывается книга целиком. Раньше показывалось «вне
        # разделов», и книга, у которой всё разложено по главам — то есть
        # обычная, — открывалась пустой страницей со словами «здесь пока
        # пусто». Оглавление сужает, а не решает, с чего начать.

        return Response(
            {
                "id": source.pk,
                "title": source.title,
                "author": source.author,
                "level": source.level,
                "may_edit": Source.objects.writable_by(request.user)
                .filter(pk=source.pk)
                .exists(),
                "outline": services.outline_of(source),
                "entries": [
                    {
                        "id": entry.pk,
                        "label": entry.label,
                        "page": entry.page,
                        # строка-номер может ни на что не показывать: это
                        # чистый адрес, у которого есть только пункты
                        "parent": entry.parent_id,
                        "problem": entry.problem_id,
                        "text": entry.problem.text if entry.problem_id else "",
                        "solutions": (
                            entry.problem.solutions.count() if entry.problem_id else 0
                        ),
                        # Чьё условие и живо ли оно. В подборку кладут чужое —
                        # ссылкой, — и от того, чьё оно, зависит, что с ним
                        # можно сделать: своё правится, общее только копией. А
                        # снятое (`retired`) выглядело бы обычным, хотя из
                        # поиска давно ушло.
                        "level": entry.problem.level if entry.problem_id else None,
                        "retired": bool(
                            entry.problem_id and entry.problem.retired
                        ),
                    }
                    for entry in entries[:500]
                ],
            }
        )

    def post(self, request, pk):
        """Вписать оглавление или задачи: книга заводится вставкой, не по одной."""
        source = self.find(request, pk)
        services.refuse_unless_writable(request.user, source)

        if "outline" in request.data:
            added = services.set_outline(source, request.data["outline"])
            return Response({"sections": added})

        section = None
        if request.data.get("section"):
            section = get_object_or_404(
                Section, pk=request.data["section"], source=source
            )
        added = services.add_problems(
            source,
            section=section,
            text=request.data.get("problems", ""),
            user=request.user,
        )
        return Response({"problems": added})


class ImportView(BankView):
    """
    Массовый импорт задач в книгу: таблицей, файлом или вставкой.

    Два адреса и один разбор, как у импорта учебного плана: предпросмотр
    **ничего не пишет и ни от чего не отказывается** (ошибки списком в теле —
    иначе единственным следом отказа была бы ошибка в консоли), а импорт
    пишет одной транзакцией. Половина импортированной книги хуже
    неимпортированной: непонятно, какая половина.
    """

    def post(self, request, pk):
        source = get_object_or_404(
            Source.objects.writable_by(request.user), pk=pk
        )
        rows = _rows(request)

        if request.data.get("preview"):
            return Response(importing.preview(rows))

        numbers = importing.parse_table(rows)
        made = services.write_numbers(source, numbers, user=request.user)
        return Response({"added": made}, status=201)


def _rows(request):
    """
    Ячейки: из вставленной матрицы или из файла.

    Формат один, файлов три — CSV, книга Excel и вставка из буфера. Читает
    книгу то же место, что и у плана (`plans/xlsx.py`): вторая библиотека ради
    того же самого была бы вторым местом, знающим про xlsx.
    """
    if request.data.get("rows") is not None:
        return request.data["rows"]

    uploaded = request.FILES.get("file")
    if uploaded is None:
        raise api_error(
            Codes.CSV_HEADER_INVALID,
            "Нечего читать: пришлите таблицу или файл.",
            field="rows",
        )

    import csv
    import io as streams

    data = uploaded.read()
    if uploaded.name.lower().endswith((".xlsx", ".xls")):
        from plans.xlsx import read_plan_xlsx

        return read_plan_xlsx(data, filename=uploaded.name).rows

    from plans.services import decode_csv, sniff_delimiter

    text = decode_csv(data)
    return list(csv.reader(streams.StringIO(text), delimiter=sniff_delimiter(text)))


class ProblemView(BankView):
    """Условие целиком: решения, где встречается, аналоги."""

    def get(self, request, pk):
        problem = get_object_or_404(Problem.objects.visible_to(request.user), pk=pk)
        return Response(services.problem_payload(problem, user=request.user))

    def patch(self, request, pk):
        problem = get_object_or_404(Problem.objects.visible_to(request.user), pk=pk)
        services.refuse_unless_writable(request.user, problem)

        for field in ("text", "answers"):
            if field in request.data:
                setattr(problem, field, request.data[field])
        problem.save()
        return Response(services.problem_payload(problem, user=request.user))


class SolutionsView(BankView):
    """Разборы: свой разбор к чужому условию — обычное дело."""

    def post(self, request):
        problem = get_object_or_404(
            Problem.objects.visible_to(request.user), pk=request.data.get("problem")
        )
        level = request.data.get("level") or "personal"
        if level == "system" and not request.user.is_superuser:
            api_error(
                Codes.SUPERUSER_REQUIRED,
                "Only a superuser adds to the system catalogue.",
                field="level",
            )

        solution = Solution.objects.create(
            problem=problem,
            title=(request.data.get("title") or "").strip(),
            text=request.data.get("text") or "",
            school=None if level == "system" else request.user.school,
            owner=request.user if level == "personal" else None,
            created_by=request.user,
        )
        return Response({"id": solution.pk}, status=201)

    def patch(self, request):
        solution = get_object_or_404(
            Solution.objects.visible_to(request.user), pk=request.data.get("id")
        )
        services.refuse_unless_writable(request.user, solution)

        for field in ("title", "text"):
            if field in request.data:
                setattr(solution, field, request.data[field])
        solution.save()
        return Response({"id": solution.pk})


class TagsView(BankView):
    """
    Словарь: читают все, заводит только суперпользователь.

    Закрытый словарь — решение, а не недосмотр: иначе через год будет «Виет»,
    «т. Виета» и «viete». Цена его — дверь «предложить тег», и она отдельная.
    """

    def get(self, request):
        return Response(
            {
                "tags": services.tag_tree(request.query_params.get("kind")),
                "may_edit": request.user.is_superuser,
            }
        )

    def post(self, request):
        if not request.user.is_superuser:
            api_error(
                Codes.SUPERUSER_ONLY_TAGS,
                "Only a superuser adds tags: the vocabulary is shared.",
                field="name",
            )

        parent = None
        if request.data.get("parent"):
            parent = get_object_or_404(Tag, pk=request.data["parent"])

        kind = request.data.get("kind") or (parent and parent.kind)
        if parent and parent.kind != kind:
            api_error(
                Codes.TAG_KIND_MISMATCH,
                "A tag's parent must be of the same kind.",
                field="parent",
            )

        tag = Tag.objects.create(
            kind=kind, parent=parent, name=(request.data.get("name") or "").strip()
        )
        return Response({"id": tag.pk, "name": tag.name, "kind": tag.kind}, status=201)


class TagLinkView(BankView):
    """Повесить или снять тег: у решения со знаком, у условия без."""

    def post(self, request):
        tag = get_object_or_404(Tag, pk=request.data.get("tag"))
        side = request.data.get("side") or SolutionTag.USES

        if request.data.get("solution"):
            solution = get_object_or_404(
                Solution.objects.visible_to(request.user), pk=request.data["solution"]
            )
            services.refuse_unless_writable(request.user, solution)
            if tag.kind not in ON_SOLUTION:
                api_error(
                    Codes.TAG_KIND_MISMATCH,
                    "A tag of that kind belongs on a problem, not a solution.",
                    field="tag",
                )
            if side == SolutionTag.AVOIDS and tag.kind not in NEGATABLE:
                api_error(
                    Codes.TAG_NOT_NEGATABLE,
                    "Only a method or a theorem can be deliberately avoided.",
                    field="side",
                )
            SolutionTag.objects.update_or_create(
                solution=solution, tag=tag, defaults={"side": side}
            )
            return Response({"ok": True})

        problem = get_object_or_404(
            Problem.objects.visible_to(request.user), pk=request.data.get("problem")
        )
        services.refuse_unless_writable(request.user, problem)
        if tag.kind not in ON_PROBLEM:
            api_error(
                Codes.TAG_KIND_MISMATCH,
                "A tag of that kind belongs on a solution, not a problem.",
                field="tag",
            )
        ProblemTag.objects.get_or_create(problem=problem, tag=tag)
        return Response({"ok": True})

    def delete(self, request):
        # Снятие тега — такая же правка, как навешивание, и права у неё те же.
        # Пока проверки тут не было, любой учитель школы мог раздеть системную
        # задачу — молча и без следа: снятая связь ничего о себе не оставляет.
        if request.data.get("solution"):
            solution = get_object_or_404(
                Solution.objects.visible_to(request.user), pk=request.data["solution"]
            )
            services.refuse_unless_writable(request.user, solution)
            SolutionTag.objects.filter(
                solution=solution, tag_id=request.data.get("tag")
            ).delete()
        else:
            problem = get_object_or_404(
                Problem.objects.visible_to(request.user), pk=request.data.get("problem")
            )
            services.refuse_unless_writable(request.user, problem)
            ProblemTag.objects.filter(
                problem=problem, tag_id=request.data.get("tag")
            ).delete()
        return Response(status=204)


class SearchView(BankView):
    """
    Поиск по граням и по тексту.

    Один эндпоинт на оба, потому что это один вопрос: набор задач сужается и
    словом, и тегом, вперемешку. Два эндпоинта означали бы, что где-то на
    экране их результаты придётся склеивать руками.
    """

    def get(self, request):
        return Response(search.payload(request.user, request.query_params))

    def post(self, request):
        """
        Поиск выражением. Телом, а не строкой запроса: дерево в query-строке
        пришлось бы кодировать, и адрес перестал бы читаться глазами — а
        читают его как раз тогда, когда разбираются, почему нашлось не то.
        """
        node = request.data.get("expression") or {}
        found = expressions.find(request.user, node)
        named = expressions.mentioned(node)
        return Response(
            search.shape(
                found,
                chosen_tags=named[""],
                chosen_uses=named["uses"],
                chosen_avoids=named["avoids"],
            )
        )


class TopicsView(BankView):
    """
    Дерево тем: общие, школьные и свои — одним списком с уровнями.

    Тема и сохранённый поиск — одна вещь: названное условие с местом в дереве.
    Общие ведёт суперпользователь, школьные — администратор, свои человек
    называет как хочет; родителем своей темы может быть общая — тогда своя
    ветка живёт внутри общего каталога и сужает его.
    """

    def get(self, request):
        found = list(Topic.objects.visible_to(request.user))
        mine = writable_ids(Topic, request.user, found)
        return Response({"topics": topics.tree(found, mine)})

    def post(self, request):
        parent = None
        if request.data.get("parent"):
            parent = get_object_or_404(
                Topic.objects.visible_to(request.user), pk=request.data["parent"]
            )

        title = (request.data.get("title") or "").strip()
        if not title:
            raise api_error(
                Codes.SEARCH_NAME_REQUIRED,
                "У темы должно быть имя — по нему её и найдут.",
                field="title",
            )

        expression = request.data.get("expression") or {}
        if expression:
            expressions.compile_(expression)

        level = request.data.get("level") or "personal"
        topic = Topic(
            title=title,
            parent=parent,
            expression=expression,
            school=None if level == "system" else request.user.school,
            owner=None if level in ("system", "school") else request.user,
            created_by=request.user,
        )
        topic.save()
        if not Topic.objects.writable_by(request.user).filter(pk=topic.pk).exists():
            # Заявленный уровень человеку не по чину. Заводить молча на
            # уровень ниже нельзя: он назвал место, и место должно быть тем.
            topic.delete()
            raise api_error(Codes.BANK_READ_ONLY, "Заводить сюда может не всякий.")
        return Response(topics.payload(topic, mine=True), status=201)


class TopicView(BankView):
    """
    Одна тема: что в ней лежит, и правка — если она моя.

    Курс и урок спрашиваются, только когда условие про пройденное: без них
    закрытая тема честно отвечает «ничего», и это правда, просто бесполезная.
    """

    def find(self, request, pk, *, writing=False):
        source = (
            Topic.objects.writable_by(request.user)
            if writing
            else Topic.objects.visible_to(request.user)
        )
        return get_object_or_404(source, pk=pk)

    def get(self, request, pk):
        topic = self.find(request, pk)
        course, upto = _where_in_the_year(request)
        condition = topic.condition()

        allowed = topics.covered(course, upto) if course else set()
        found = (
            expressions.find(request.user, condition, allowed=allowed)
            if condition
            else Problem.objects.visible_to(request.user).filter(retired=False)
        )
        return Response(
            {
                **topics.payload(
                    topic,
                    mine=Topic.objects.writable_by(request.user)
                    .filter(pk=topic.pk)
                    .exists(),
                ),
                "needs_course": expressions.mentions_covered(condition),
                **search.shape(found),
            }
        )

    def patch(self, request, pk):
        topic = self.find(request, pk, writing=True)
        if "title" in request.data:
            topic.title = (request.data["title"] or "").strip()
        if "expression" in request.data:
            expressions.compile_(request.data["expression"] or {})
            topic.expression = request.data["expression"] or {}
        if "parent" in request.data:
            topic.parent = (
                get_object_or_404(
                    Topic.objects.visible_to(request.user), pk=request.data["parent"]
                )
                if request.data["parent"]
                else None
            )
        topic.save()
        return Response(topics.payload(topic, mine=True))

    def delete(self, request, pk):
        topics.remove(self.find(request, pk, writing=True))
        return Response(status=204)


class CopyView(BankView):
    """
    Взять чужое к себе: задачу или раздел целиком.

    Куда — спрашивается всегда, потому что «своя книга» у человека не одна и
    молчаливое «в первую попавшуюся» означало бы искать потом руками.
    """

    def post(self, request):
        into = get_object_or_404(
            Source.objects.writable_by(request.user), pk=request.data.get("into")
        )
        mode = request.data.get("mode") or copying.LINK

        if request.data.get("section"):
            section = get_object_or_404(
                Section.objects.filter(
                    source__in=Source.objects.visible_to(request.user)
                ),
                pk=request.data["section"],
            )
            made = copying.copy_section(
                section, into=into, mode=mode, user=request.user
            )
            return Response({"section": made.pk}, status=201)

        # Берут пачкой: главу, вариант, десяток отобранного из поиска. По
        # одной — тоже, и это тот же путь с одним элементом.
        wanted = request.data.get("problems") or [request.data.get("problem")]
        found = Problem.objects.visible_to(request.user).in_bulk(
            [one for one in wanted if one]
        )
        chosen = [found[one] for one in wanted if one in found]
        if not chosen:
            raise api_error(
                Codes.BANK_NOTHING_TO_COPY,
                "Не выбрано ни одной задачи: брать нечего.",
                field="problems",
            )

        section = None
        if request.data.get("into_section"):
            section = get_object_or_404(
                Section.objects.filter(source=into), pk=request.data["into_section"]
            )

        entries = [
            copying.copy_problem(
                problem,
                into=into,
                mode=mode,
                label=request.data.get("label") or "",
                section=section,
                user=request.user,
            )
            for problem in chosen
        ]
        return Response(
            {
                "taken": len(entries),
                "entry": entries[0].pk,
                "problem": entries[0].problem_id,
            },
            status=201,
        )


class AnalogueView(BankView):
    """
    Аналоги: те же задачи с другими числами.

    Объявляет их человек, и это утверждение о **условиях**, а не о том, откуда
    взялась копия: происхождение живёт отдельным полем и в семью не идёт.
    """

    def post(self, request):
        mine = Problem.objects.visible_to(request.user)
        problem = get_object_or_404(mine, pk=request.data.get("problem"))
        other = get_object_or_404(mine, pk=request.data.get("other"))
        services.refuse_unless_writable(request.user, problem)

        family = copying.join_family(problem, other, user=request.user)
        return Response({"family": family.pk}, status=201)

    def delete(self, request):
        problem = get_object_or_404(
            Problem.objects.visible_to(request.user), pk=request.data.get("problem")
        )
        services.refuse_unless_writable(request.user, problem)
        copying.leave_family(problem)
        return Response(status=204)


def _where_in_the_year(request):
    """
    Курс и урок из строки запроса — оба только среди своих.

    Нужны они одному листу выражения — «не выходит за пройденное»: пройденное
    приходит извне, из хронологии плана, и другого источника у него нет.
    """
    from plans.models import PlanNode
    from schedule.models import Course

    course = None
    upto = None
    if request.query_params.get("course"):
        course = get_object_or_404(
            Course.objects.for_teacher(request.user),
            pk=request.query_params["course"],
        )
    if course and request.query_params.get("upto"):
        upto = get_object_or_404(
            PlanNode.objects.filter(course=course), pk=request.query_params["upto"]
        )
    return course, upto


class ChronologyView(BankView):
    """
    План курса как хронология понятий: где что вводится.

    Правит её ведущий курса — это разметка **его** программы, а не общего
    словаря. Тег при этом берётся из общего: своих понятий не заводят.
    """

    def get(self, request, course):
        course = self.course(request, course)
        return Response({"lessons": topics.chronology(course)})

    def post(self, request, course):
        course = self.course(request, course, writing=True)
        from plans.models import PlanNode

        node = get_object_or_404(
            PlanNode.objects.filter(course=course, is_section=False),
            pk=request.data.get("node"),
        )
        tag = get_object_or_404(Tag, pk=request.data.get("tag"))
        topics.introduce(course, node, tag)
        return Response({"lessons": topics.chronology(course)}, status=201)

    def delete(self, request, course):
        course = self.course(request, course, writing=True)
        Introduction.objects.filter(
            course=course, tag_id=request.data.get("tag")
        ).delete()
        return Response(status=204)

    def course(self, request, pk, *, writing=False):
        from schedule.models import Course

        source = (
            Course.objects.writable_by(request.user)
            if writing
            else Course.objects.for_teacher(request.user)
        )
        return get_object_or_404(source, pk=pk)


class ProposalsView(BankView):
    """
    Предложения: сообщить об опечатке, предложить тег, задачу или разбор.

    Закрытость общего каталога стоила ровно этого — учителю нечего было
    сделать с чужой ошибкой, кроме копии. Дверь односторонняя только на вид:
    разбирающий отвечает, автор видит ответ, и оба пишут реплики.

    Список показывает **две разные вещи** одним адресом: «мои» — то, что я
    предложил, и «на разбор» — то, что мне разбирать. Разделять их
    эндпоинтами было бы честно ровно до первого экрана, где нужны оба.
    """

    def get(self, request):
        mine = Proposal.objects.filter(author=request.user).select_related(
            "problem", "solution", "tag", "author"
        )
        return Response(
            {
                "mine": [proposals.payload(one, user=request.user) for one in mine],
                "waiting": [
                    proposals.payload(one, user=request.user)
                    for one in proposals.waiting_for(request.user)
                ],
            }
        )

    def post(self, request):
        made = proposals.make(
            request.user,
            kind=request.data.get("kind") or Proposal.OTHER,
            text=request.data.get("text") or "",
            suggested=request.data.get("suggested") or "",
            problem=self.find(Problem, request, "problem"),
            solution=self.find(Solution, request, "solution"),
            tag=self.find(Tag, request, "tag", visible=False),
            level=request.data.get("level"),
        )
        return Response(proposals.payload(made, user=request.user), status=201)

    def find(self, model, request, field, *, visible=True):
        """
        Цель предложения — только из того, что человеку видно.

        Иначе предложение стало бы способом узнать о существовании чужого:
        «сообщил об опечатке в задаче номер такой-то» и по ответу понял, что
        она есть.
        """
        if not request.data.get(field):
            return None
        source = model.objects.visible_to(request.user) if visible else model.objects
        return get_object_or_404(source, pk=request.data[field])


class ProposalView(BankView):
    """Один разговор: реплика, принятие, отказ."""

    def get_object(self, request, pk):
        found = get_object_or_404(Proposal, pk=pk)
        if found.author_id != request.user.pk and not proposals.may_resolve(
            request.user, found
        ):
            # чужое предложение неотличимо от несуществующего — как везде
            raise Http404
        return found

    def get(self, request, pk):
        return Response(
            proposals.payload(self.get_object(request, pk), user=request.user)
        )

    def post(self, request, pk):
        """Реплика в разговоре: её пишут обе стороны."""
        found = self.get_object(request, pk)
        proposals.say(found, request.user, request.data.get("text") or "")
        return Response(proposals.payload(found, user=request.user), status=201)

    def patch(self, request, pk):
        """Решение: принять (и сделать) или отклонить (со словами)."""
        found = self.get_object(request, pk)
        if not proposals.may_resolve(request.user, found):
            api_error(
                Codes.BANK_READ_ONLY,
                "Разбирает тот, кто вправе править: у общего каталога это "
                "суперпользователь, у школьного — администратор школы.",
                field="state",
            )

        if request.data.get("state") == Proposal.ACCEPTED:
            proposals.accept(
                found,
                request.user,
                answer=request.data.get("answer") or "",
                tag_kind=request.data.get("tag_kind"),
                side=request.data.get("side"),
            )
        else:
            proposals.decline(
                found, request.user, answer=request.data.get("answer") or ""
            )

        return Response(proposals.payload(found, user=request.user))
