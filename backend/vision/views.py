"""
Расход на чтение сканов: потолок и журнал.

Два вопроса и два хозяина. Администратор спрашивает «сколько школа потратила и
не пора ли поднять потолок» — и видит весь журнал. Учитель спрашивает «во что
обошлась вот эта пачка» — и видит свои строки. Это один и тот же журнал,
просто суженный: два эндпоинта разошлись бы в первой же правке.
"""

from config.access import IsSchoolAdmin, IsSchoolMember, IsTeacher
from config.errors import Codes, api_error
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import AiSpend

# Сколько строк журнала отдаём. Экран показывает последнее, а не всё за год:
# «сколько всего» отвечает сводка, а не длина списка.
RECENT = 50


class BudgetView(APIView):
    """Потолок школы: читают все свои, ставит администратор."""

    permission_classes = [IsAuthenticated, IsSchoolMember, IsTeacher]

    def get(self, request):
        school = request.user.school
        return Response(
            services.budget(school)
            | {"limit_cents": school.ai_month_limit_cents, "may_edit": request.user.is_school_admin}
        )

    def patch(self, request):
        if not request.user.is_school_admin:
            api_error(
                Codes.SCHOOL_ADMIN_REQUIRED,
                "Only a school administrator can change the limit.",
                field="limit_cents",
            )

        school = request.user.school
        raw = request.data.get("limit_cents")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            limit = -1
        if limit < 0:
            api_error(
                Codes.AI_LIMIT_NEGATIVE,
                "The limit is a whole number of cents, zero or more.",
                field="limit_cents",
            )

        school.ai_month_limit_cents = limit
        school.save(update_fields=["ai_month_limit_cents"])
        return Response(
            services.budget(school) | {"limit_cents": limit, "may_edit": True}
        )


class SpendView(APIView):
    """Журнал трат: администратору все строки школы, учителю свои."""

    permission_classes = [IsAuthenticated, IsSchoolMember, IsTeacher]

    def get(self, request):
        rows = AiSpend.objects.filter(school=request.user.school).select_related(
            "user", "work"
        )
        mine = request.query_params.get("mine") == "true"
        if mine or not request.user.is_school_admin:
            rows = rows.filter(user=request.user)

        return Response(
            {
                "budget": services.budget(request.user.school),
                "rows": [
                    {
                        "id": row.pk,
                        "at": row.created_at,
                        "who": (row.user and row.user.get_full_name()) or "",
                        "work": row.work_id,
                        "work_title": (row.work and row.work.title) or "",
                        "purpose": row.purpose,
                        "model": row.model,
                        "cost_micros": row.cost_micros,
                    }
                    for row in rows[:RECENT]
                ],
            }
        )
