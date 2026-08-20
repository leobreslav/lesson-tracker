"""
Банк задач: источники, условия, решения и словарь.

Права тут не по виду пользователя, а по владению: системное правит
суперпользователь, школьное и личное — администратор школы, личное — ещё и
автор. Поэтому вьюхи стоят на `IsTeacher` (ученику банк не показывают вовсе),
а внутри спрашивают `writable_by`.
"""

from config.access import IsSchoolMember, IsTeacher
from config.errors import Codes, api_error
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import copying, expressions, search, services
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
    SavedSearch,
    Source,
    Tag,
)


class BankView(APIView):
    """Общая рамка: банк — учительская часть, ученику его не показывают."""

    permission_classes = [IsAuthenticated, IsSchoolMember, IsTeacher]


class SourcesView(BankView):
    """Полка источников: системные, школьные и свои."""

    def get(self, request):
        sources = Source.objects.visible_to(request.user).prefetch_related("entries")
        return Response(
            {
                "sources": [
                    {
                        "id": source.pk,
                        "title": source.title,
                        "author": source.author,
                        "level": source.level,
                        "problems": source.entries.count(),
                        "may_edit": Source.objects.writable_by(request.user)
                        .filter(pk=source.pk)
                        .exists(),
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

        entries = source.entries.select_related("problem", "section")
        if label:
            # номер — это адрес, а не текст: «14а» ищется точным совпадением
            entries = entries.filter(label__iexact=label)
        elif section:
            entries = entries.filter(section_id=section)
        elif source.sections.exists():
            # книга с оглавлением: без выбранного раздела показываем то, что
            # лежит вне разделов, а не всё подряд
            entries = entries.filter(section__isnull=True)

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
                        "problem": entry.problem_id,
                        "text": entry.problem.text,
                        "solutions": entry.problem.solutions.count(),
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


class ProblemView(BankView):
    """Условие целиком: решения, где встречается, аналоги."""

    def get(self, request, pk):
        problem = get_object_or_404(Problem.objects.visible_to(request.user), pk=pk)
        return Response(services.problem_payload(problem, user=request.user))

    def patch(self, request, pk):
        problem = get_object_or_404(Problem.objects.visible_to(request.user), pk=pk)
        services.refuse_unless_writable(request.user, problem)

        for field in ("text", "answer"):
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
        if request.data.get("solution"):
            SolutionTag.objects.filter(
                solution_id=request.data["solution"], tag_id=request.data.get("tag")
            ).delete()
        else:
            ProblemTag.objects.filter(
                problem_id=request.data.get("problem"), tag_id=request.data.get("tag")
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


class SavedSearchesView(BankView):
    """Сохранённые запросы: свои, школьные и системные."""

    def get(self, request):
        return Response(
            {
                "searches": [
                    _saved(saved, request.user)
                    for saved in SavedSearch.objects.visible_to(request.user)
                ]
            }
        )

    def post(self, request):
        name = (request.data.get("name") or "").strip()
        if not name:
            raise api_error(
                Codes.SEARCH_NAME_REQUIRED,
                "У сохранённого поиска должно быть имя — по нему его и найдут.",
            )
        node = request.data.get("expression") or {}
        # Кривое выражение отклоняется здесь, а не при первом открытии:
        # сохранённый поиск, который не ищет, — худший вид мусора.
        expressions.compile_(node)

        saved = SavedSearch.objects.create(
            name=name,
            expression=node,
            school=None if request.data.get("level") == "system" else request.user.school,
            owner=None if request.data.get("level") in ("system", "school") else request.user,
            created_by=request.user,
        )
        if not SavedSearch.objects.writable_by(request.user).filter(pk=saved.pk).exists():
            # Заявленный уровень человеку не по чину — не заводим молча на
            # уровень ниже: он назвал место, и место должно быть тем.
            saved.delete()
            raise api_error(
                Codes.BANK_READ_ONLY, "Сохранять сюда может не всякий."
            )
        return Response(_saved(saved, request.user), status=201)


class SavedSearchView(BankView):
    """Один сохранённый запрос: переименовать, уточнить, убрать."""

    def get_object(self, request, pk, *, writing=False):
        source = SavedSearch.objects.writable_by(request.user) if writing else SavedSearch.objects.visible_to(request.user)
        return get_object_or_404(source, pk=pk)

    def patch(self, request, pk):
        saved = self.get_object(request, pk, writing=True)
        if "name" in request.data:
            saved.name = (request.data["name"] or "").strip()
        if "expression" in request.data:
            expressions.compile_(request.data["expression"] or {})
            saved.expression = request.data["expression"]
        saved.save(update_fields=["name", "expression"])
        return Response(_saved(saved, request.user))

    def delete(self, request, pk):
        self.get_object(request, pk, writing=True).delete()
        return Response(status=204)


def _saved(saved, user):
    return {
        "id": saved.pk,
        "name": saved.name,
        "level": saved.level,
        "expression": saved.expression,
        "may_edit": SavedSearch.objects.writable_by(user).filter(pk=saved.pk).exists(),
    }


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

        problem = get_object_or_404(
            Problem.objects.visible_to(request.user), pk=request.data.get("problem")
        )
        section = None
        if request.data.get("into_section"):
            section = get_object_or_404(
                Section.objects.filter(source=into), pk=request.data["into_section"]
            )
        entry = copying.copy_problem(
            problem,
            into=into,
            mode=mode,
            label=request.data.get("label") or "",
            section=section,
            user=request.user,
        )
        return Response({"entry": entry.pk, "problem": entry.problem_id}, status=201)


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
