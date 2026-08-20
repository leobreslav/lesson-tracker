"""
Справочник систем оценивания: читают все свои, правит администратор.

Читать нужно каждому учителю — он выбирает систему на своей работе, — а
править школьный справочник может только администратор. Это ровно та же форма
доступа, что у предметов и параллелей, и берётся она тем же классом.
"""

from config.access import IsSchoolAdminForWrite, IsSchoolMember, IsTeacher
from config.errors import Codes, api_error
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import grading
from .models import GradeBand, GradingSystem


class GradingSystemsView(APIView):
    """Список систем школы, заведение и типовой набор."""

    permission_classes = [
        IsAuthenticated,
        IsSchoolMember,
        IsTeacher,
        IsSchoolAdminForWrite,
    ]

    def get(self, request):
        school = request.user.school
        return Response(
            {
                "systems": [
                    grading.payload(system)
                    for system in school.grading_systems.prefetch_related("bands")
                ],
                "default": school.default_grading_system_id,
                "year": school.year_grading_system_id,
                "may_edit": request.user.is_school_admin,
            }
        )

    def post(self, request):
        school = request.user.school

        if request.data.get("typical"):
            added = grading.add_typical(school, request.user.language)
            return Response({"added": added})

        name = (request.data.get("name") or "").strip()
        if not name:
            api_error(
                Codes.GRADING_NAME_REQUIRED,
                "A grading system needs a name.",
                field="name",
            )
        if school.grading_systems.filter(name=name).exists():
            api_error(
                Codes.GRADING_NAME_TAKEN,
                "The school already has a grading system with that name.",
                field="name",
            )

        system = GradingSystem.objects.create(
            school=school,
            name=name,
            kind=request.data.get("kind") or GradingSystem.POINTS,
        )
        return Response(grading.payload(system), status=201)


class GradingSystemView(APIView):
    """Одна система: полосы, разрешение, умолчания школы."""

    permission_classes = [
        IsAuthenticated,
        IsSchoolMember,
        IsTeacher,
        IsSchoolAdminForWrite,
    ]

    def get_object(self, request, pk):
        system = GradingSystem.objects.filter(
            pk=pk, school=request.user.school
        ).first()
        if system is None:
            api_error(Codes.OTHER_SCHOOL, "No such grading system.", field="id")
        return system

    def patch(self, request, pk):
        system = self.get_object(request, pk)

        if "name" in request.data:
            system.name = (request.data["name"] or "").strip() or system.name
        if "is_allowed" in request.data:
            system.is_allowed = bool(request.data["is_allowed"])
        if "top_level" in request.data:
            system.top_level = int(request.data["top_level"])
        system.save()

        if "bands" in request.data:
            grading.set_bands(system, request.data["bands"])

        school = request.user.school
        if request.data.get("as_default"):
            school.default_grading_system = system
            school.save(update_fields=["default_grading_system"])
        if request.data.get("as_year"):
            school.year_grading_system = system
            school.save(update_fields=["year_grading_system"])

        return Response(grading.payload(system))

    def delete(self, request, pk):
        system = self.get_object(request, pk)
        # работы, которые ею оценивались, остаются: отметка выводится, а не
        # хранится, и без системы у них просто не станет отметки
        system.delete()
        return Response(status=204)
