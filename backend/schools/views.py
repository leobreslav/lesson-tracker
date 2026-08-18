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
from django.utils import timezone
from django.db.models import Count, ProtectedError
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
        from schedule.models import Course, CourseAssignment, GradeLevel, Subject
        from schedule.models import Slot

        school = request.user.school
        year = (
            SchoolYear.objects.filter(school=school).order_by("-start_date").first()
        )
        courses = Course.objects.filter(school=school)
        # расписание школы — это все уроки её курсов: отдельной таблицы у
        # него больше нет
        lessons = Slot.objects.filter(course__school=school)

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
                "master_slots": lessons.count(),
                "master_slots_unassigned": lessons.filter(
                    course__assignments=None
                ).count(),
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
    queryset = (
        School.objects.prefetch_related("members")
        .annotate(member_count=Count("members"))
        .order_by("name")
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

        # Учётка заводится сразу, как и у обычного приглашения: у новой школы
        # иначе не существует никого, кем её можно было бы наполнить до
        # первого входа администратора.
        person = User.objects.filter(email__iexact=email).first()
        if person is None:
            services.provision(
                school, email, kind=User.Kind.TEACHER, is_admin=True
            )
        elif person.school_id is None:
            person.school = school
            person.is_school_admin = True
            person.save(update_fields=["school", "is_school_admin"])

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
        """
        Люди школы одного вида: по умолчанию сотрудники.

        Один вьюсет на оба списка, потому что вопрос один — «кто здесь», — а
        различаются они только тем, чем человек связан с курсами: учитель
        назначением, ученик зачислением. Умолчание учительское намеренно:
        роль администратора и школьное расписание спрашивают именно
        сотрудников, и адрес без параметра должен отвечать им.
        """
        people = User.objects.filter(
            school_id=self.request.user.school_id
        ).order_by("first_name", "last_name", "email")

        # сужает только список: человек, найденный по id, — участник этой
        # школы, и вид его известен из него самого
        if self.action == "list":
            kind = self.request.query_params.get("kind") or User.Kind.TEACHER
            people = people.filter(
                kind=kind if kind in User.Kind.values else User.Kind.TEACHER
            )

        return people.prefetch_related("course_assignments__course", "enrolments__course")

    def perform_destroy(self, instance):
        """
        Detaching a person from the school. Their work is not deleted.

        `school` is set to None and the assignments go with them, because an
        assignment is a statement about this school. The lessons and the plan
        stay: they are the person's own, and «remove from the list» must not
        mean «erase a year of teaching». The school timetable keeps their
        rows too: расписание принадлежит курсу и остаётся на нём — курс
        просто становится курсом без ведущего.

        The first attempt is refused with the counts; `?force=true` confirms.
        """
        from schedule.models import CourseAssignment, Slot

        if instance.pk == self.request.user.pk:
            api_error(
                Codes.LAST_ADMIN,
                "You cannot detach yourself from the school.",
            )

        if instance.is_student:
            return self.detach_student(instance)

        # строки плана здесь не считаются: план принадлежит курсу, а не
        # человеку, и отвязка его не касается — курс останется без ведущего,
        # а программа на нём цела
        slots = Slot.objects.filter(teacher=instance).count()
        courses = CourseAssignment.objects.filter(teacher=instance).count()

        forced = self.request.query_params.get("force", "").lower() == "true"
        if (slots or courses) and not forced:
            api_error(
                Codes.MEMBER_IN_USE,
                f"{instance.email} teaches {courses} courses and has {slots} "
                "lessons. Detaching keeps all of it but removes their "
                "assignments; repeat with force=true to confirm.",
                email=instance.email,
                courses=courses,
                slots=slots,
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

    def detach_student(self, instance):
        """
        То же самое для ученика, и по той же причине два разных действия.

        Зачисление — утверждение об этой школе, поэтому уходит вместе с
        ней: ученик снимается со всех курсов. Но **строки остаются** — они
        и есть след того, что человек здесь учился, и к ним будут привязаны
        его ответы. Снятие, а не удаление, ровно как когда его снимают с
        одного курса.
        """
        from schedule.models import CourseStudent

        rows = CourseStudent.objects.filter(
            student=instance, removed_at__isnull=True
        )
        courses = rows.count()

        forced = self.request.query_params.get("force", "").lower() == "true"
        if courses and not forced:
            api_error(
                Codes.MEMBER_IN_USE,
                f"{instance.email} is enrolled in {courses} courses. "
                "Detaching keeps what they have done but takes them off "
                "every course; repeat with force=true to confirm.",
                email=instance.email,
                courses=courses,
                slots=0,
            )

        with transaction.atomic():
            rows.update(removed_at=timezone.now())
            instance.school = None
            instance.save(update_fields=["school"])


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

    Править в приглашении нечего: адрес, вид и роль — то, за что поручились,
    когда его писали, а курсы теперь висят на самой учётке, которую оно
    завело.
    """

    serializer_class = InvitationSerializer
    # admins in both directions, so IsSchoolAdmin rather than …ForWrite
    permission_classes = [IsAuthenticated, IsSchoolMember, IsTeacher, IsSchoolAdmin]

    def get_queryset(self):
        queryset = Invitation.objects.filter(school_id=self.request.user.school_id)

        # два списка, а не один: во вкладке учителей ученикам делать нечего,
        # а в составе курса — учителям
        kind = self.request.query_params.get("kind")
        if kind:
            queryset = queryset.filter(kind=kind)

        return queryset

    def perform_create(self, serializer):
        """
        Приглашение заводит человека, а не только строку.

        Учётка появляется сразу и целиком: школа, вид, роль. Дальше её
        назначают на курсы и записывают в курсы обычными таблицами — то
        есть подготовить всё можно до того, как человек впервые войдёт.
        Войти в неё при этом нельзя ничем, кроме Google с этим же адресом.
        """
        school = self.request.user.school
        invitation = serializer.save(school=school, created_by=self.request.user)
        services.provision(
            school,
            invitation.email,
            kind=invitation.kind,
            name=invitation.name,
            is_admin=invitation.is_school_admin,
        )
