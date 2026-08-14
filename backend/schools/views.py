from config.access import (
    IsSchoolAdmin,
    IsSchoolAdminForWrite,
    IsSchoolMember,
    IsSuperuser,
    IsTeacher,
)
from collections import Counter

from config.errors import Codes, api_error
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import ProtectedError
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import Invitation, School
from .serializers import (
    InvitationSerializer,
    MemberSerializer,
    SchoolInviteSerializer,
    SchoolSerializer,
)

User = get_user_model()


def describe(blocked: ProtectedError) -> str:
    """«2 members, 3 files» — what a ProtectedError is actually about."""
    counts = Counter(
        obj._meta.verbose_name_plural for obj in blocked.protected_objects
    )
    return ", ".join(f"{count} {name}" for name, count in sorted(counts.items()))


class MySchoolView(RetrieveUpdateAPIView):
    """
    The school of the requester: everybody reads it, its admins rename it.

    A school object like any other, so it goes through the same permission
    as the calendar and the courses.
    """

    serializer_class = SchoolSerializer
    permission_classes = [
        IsAuthenticated,
        IsSchoolMember,
        IsTeacher,
        IsSchoolAdminForWrite,
    ]
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        return self.request.user.school


class SchoolOverviewView(APIView):
    """
    The state of the school in one request: what is set up and what is not.

    The «Overview» page is built from this rather than from five separate
    lists — it shows counts, not rows, and five requests for five numbers is
    five chances to show a half-drawn page.
    """

    permission_classes = [IsAuthenticated, IsSchoolMember, IsTeacher]

    def get(self, request):
        from calendars.models import SchoolYear
        from schedule.models import Course, CourseAssignment, GradeLevel, MasterSlot, Subject

        school = request.user.school
        year = (
            SchoolYear.objects.filter(school=school).order_by("-start_date").first()
        )
        courses = Course.objects.filter(school=school)
        master = MasterSlot.objects.filter(school=school)

        return Response(
            {
                "school": {"id": school.pk, "name": school.name},
                "teachers": User.objects.filter(
                    school=school, kind=User.Kind.TEACHER
                ).count(),
                "admins": User.objects.filter(
                    school=school, is_school_admin=True
                ).count(),
                "invitations": Invitation.objects.filter(
                    school=school, accepted_at__isnull=True
                ).count(),
                "courses": courses.count(),
                "courses_without_teacher": courses.filter(
                    assignments__isnull=True
                ).count(),
                "assignments": CourseAssignment.objects.filter(
                    course__school=school
                ).count(),
                "subjects": Subject.objects.filter(school=school).count(),
                "grades": GradeLevel.objects.filter(school=school).count(),
                "year": (
                    None
                    if year is None
                    else {
                        "id": year.pk,
                        "name": year.name,
                        "start_date": year.start_date,
                        "end_date": year.end_date,
                        "terms": year.terms.count(),
                    }
                ),
                "master_slots": master.count(),
                "master_slots_unassigned": master.filter(teacher__isnull=True).count(),
            }
        )


class SchoolViewSet(viewsets.ModelViewSet):
    """
    Every school, for a superuser.

    This is the one section where `is_superuser` means something inside the
    app. Creating a school cannot come from within a school, and the first
    administrator cannot invite themselves, so somebody outside the schools
    has to do both — otherwise every new school would need a trip to
    /admin/.

    A superuser is still an ordinary member of their own school everywhere
    else: this viewset hands out schools, not power over the work inside
    them.
    """

    serializer_class = SchoolSerializer
    permission_classes = [IsAuthenticated, IsSuperuser]
    queryset = School.objects.prefetch_related("members").order_by("name")

    def perform_destroy(self, instance):
        """
        A school with anything in it stays. Several PROTECTs say so.

        People are the usual blocker — deleting the school would strand their
        calendar, courses and lessons — but not the only one: subjects and
        stored files hold it too, and a school can outlive its last member.
        So the answer names what is actually in the way rather than assuming
        it is people; a message that says «2 members» about three files sends
        somebody looking in the wrong place.
        """
        try:
            instance.delete()
        except ProtectedError as blocked:
            api_error(
                Codes.SCHOOL_IN_USE,
                f"«{instance.name}» is still in use: {describe(blocked)}. "
                "Clear it first.",
                name=instance.name,
                members=instance.members.count(),
                blocked_by=describe(blocked),
            )

    @action(detail=True, methods=["post"])
    def invite(self, request, pk=None):
        """
        Invite the first administrator of a school.

        The same invitation a school admin would write, only from outside:
        the person signs in through Google on that address and arrives with
        the role already granted.
        """
        school = self.get_object()
        form = SchoolInviteSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        email = form.validated_data["email"]

        invitation, created = Invitation.objects.get_or_create(
            school=school,
            email=email,
            defaults={"is_school_admin": True, "created_by": request.user},
        )
        if not created and not invitation.is_school_admin:
            # the address was already invited as a plain teacher — promote it
            invitation.is_school_admin = True
            invitation.save(update_fields=["is_school_admin"])

        return Response(
            InvitationSerializer(invitation).data, status=201 if created else 200
        )


class MemberViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    The people of the school.

    Everybody sees the list — knowing who else teaches here is not a secret
    and the schedule shows their names anyway. Only an administrator hands
    the role over or detaches somebody.
    """

    serializer_class = MemberSerializer
    permission_classes = [
        IsAuthenticated,
        IsSchoolMember,
        IsTeacher,
        IsSchoolAdminForWrite,
    ]
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        # участники — это сотрудники: ученики той же школы сюда не попадают
        # и роль администратора получить не могут
        return (
            User.objects.filter(
                school_id=self.request.user.school_id, kind=User.Kind.TEACHER
            )
            .prefetch_related("course_assignments__course")
            .order_by("first_name", "last_name", "email")
        )

    def perform_destroy(self, instance):
        """
        A school with anything in it stays. Several PROTECTs say so.

        People are the usual blocker — deleting the school would strand their
        calendar, courses and lessons — but not the only one: subjects and
        stored files hold it too, and a school can outlive its last member.
        So the answer names what is actually in the way rather than assuming
        it is people; a message that says «2 members» about three files sends
        somebody looking in the wrong place.
        """
        try:
            instance.delete()
        except ProtectedError as blocked:
            api_error(
                Codes.SCHOOL_IN_USE,
                f"«{instance.name}» is still in use: {describe(blocked)}. "
                "Clear it first.",
                name=instance.name,
                members=instance.members.count(),
                blocked_by=describe(blocked),
            )

    @action(detail=True, methods=["post"])
    def invite(self, request, pk=None):
        """
        Invite the first administrator of a school.

        The same invitation a school admin would write, only from outside:
        the person signs in through Google on that address and arrives with
        the role already granted.
        """
        school = self.get_object()
        form = SchoolInviteSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        email = form.validated_data["email"]

        invitation, created = Invitation.objects.get_or_create(
            school=school,
            email=email,
            defaults={"is_school_admin": True, "created_by": request.user},
        )
        if not created and not invitation.is_school_admin:
            # the address was already invited as a plain teacher — promote it
            invitation.is_school_admin = True
            invitation.save(update_fields=["is_school_admin"])

        return Response(
            InvitationSerializer(invitation).data, status=201 if created else 200
        )


class MemberViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    The people of the school.

    Everybody sees the list — knowing who else teaches here is not a secret
    and the schedule shows their names anyway. Only an administrator hands
    the role over or detaches somebody.
    """

    serializer_class = MemberSerializer
    permission_classes = [
        IsAuthenticated,
        IsSchoolMember,
        IsTeacher,
        IsSchoolAdminForWrite,
    ]
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        # участники — это сотрудники: ученики той же школы сюда не попадают
        # и роль администратора получить не могут
        return (
            User.objects.filter(
                school_id=self.request.user.school_id, kind=User.Kind.TEACHER
            )
            .prefetch_related("course_assignments__course")
            .order_by("first_name", "last_name", "email")
        )

    def perform_destroy(self, instance):
        """
        Detaching a teacher from the school. Their work is not deleted.

        `school` is set to None and the assignments go with them, because an
        assignment is a statement about this school. The lessons and the plan
        stay: they are the person's own, and «remove from the list» must not
        mean «erase a year of teaching». The school timetable keeps their
        rows too — `MasterSlot.teacher` is SET_NULL, so the grid survives as
        unassigned load rather than disappearing.

        The first attempt is refused with the counts; `?force=true` confirms.
        """
        from schedule.models import CourseAssignment, LessonSlot
        from plans.models import PlanNode

        if instance.pk == self.request.user.pk:
            api_error(
                Codes.LAST_ADMIN,
                "You cannot detach yourself from the school.",
            )

        slots = LessonSlot.objects.filter(teacher=instance).count()
        rows = PlanNode.objects.filter(teacher=instance).count()
        courses = CourseAssignment.objects.filter(teacher=instance).count()

        forced = self.request.query_params.get("force", "").lower() == "true"
        if (slots or rows or courses) and not forced:
            api_error(
                Codes.MEMBER_IN_USE,
                f"{instance.email} teaches {courses} courses and has {slots} "
                f"lessons and {rows} plan rows. Detaching keeps all of it but "
                "removes their assignments; repeat with force=true to confirm.",
                email=instance.email,
                courses=courses,
                slots=slots,
                plan_rows=rows,
            )

        # a person can be the last administrator only while they are here
        others = User.objects.filter(
            school_id=instance.school_id, is_school_admin=True
        ).exclude(pk=instance.pk)
        if instance.is_school_admin and not others.exists():
            api_error(
                Codes.LAST_ADMIN,
                "This is the last administrator of the school.",
            )

        # одной транзакцией: снятые назначения при оставшейся школе — это
        # состояние, неотличимое от «администратор убрал курсы руками», и
        # восстанавливать его пришлось бы по памяти
        with transaction.atomic():
            instance.course_assignments.all().delete()
            instance.school = None
            instance.is_school_admin = False
            instance.save(update_fields=["school", "is_school_admin"])


class InvitationViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    Invitations of this school.

    Administrators only, in both directions: the list of addresses somebody
    wrote down is nobody else's business.

    An accepted invitation is kept — it is the record of who let whom in.
    Deleting one only withdraws an invitation nobody has used yet; it does not
    remove a member who already joined.
    """

    serializer_class = InvitationSerializer
    # admins in both directions, so IsSchoolAdmin rather than …ForWrite
    permission_classes = [IsAuthenticated, IsSchoolMember, IsTeacher, IsSchoolAdmin]

    def get_queryset(self):
        queryset = Invitation.objects.filter(
            school_id=self.request.user.school_id
        ).prefetch_related("courses")

        # два списка, а не один: во вкладке учителей ученикам делать нечего,
        # а в составе курса — учителям
        kind = self.request.query_params.get("kind")
        if kind:
            queryset = queryset.filter(kind=kind)

        course = self.request.query_params.get("course")
        if course:
            queryset = (
                queryset.filter(courses=course)
                if course.isdigit()
                else queryset.none()
            )

        return queryset

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.action == "list":
            # пометка «этот адрес уже в другой школе» — одним запросом на
            # весь список, а не по запросу на строку
            context["conflicts"] = services.conflicting_addresses(self.get_queryset())
        return context

    def perform_create(self, serializer):
        serializer.save(
            school=self.request.user.school, created_by=self.request.user
        )
