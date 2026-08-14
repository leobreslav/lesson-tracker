"""
Who may see and change what.

Пользователей два вида, и это первое, что здесь проверяется. Ученик —
не роль внутри учительского интерфейса, а другой интерфейс целиком: ни
расписания, ни планов, ни библиотеки он видеть не должен. Принадлежность
школе перестала означать «сотрудник», поэтому `IsSchoolMember` больше не
значит «можно» — рядом с ним стоит `IsTeacher`.

There are exactly four access shapes in the project, and they live here
rather than in twenty querysets:

1. a school object, reading — the user belongs to the same school;
2. a school object, writing — plus the administrator role;
3. a personal object — it belongs to this teacher, inside a course of their
   own school;
4. объект курса — читает тот, кто в курсе работает, пишет назначенный
   ведущий учитель. Так устроены учебный план и работы: они принадлежат
   курсу, а ведущий у курса один.

Every viewset picks a base class below and says which ORM path leads from its
model to the school (``school_path``), to the teacher (``teacher_path``) or
to the course (``course_path``).
Nothing else filters by hand: a forgotten filter is exactly the hole this
module exists to close.

Two different refusals, on purpose:

* a foreign school gives **404** — the object is not in the queryset at all,
  and a stranger should not learn that it exists;
* one's own school without the role gives **403** — the object is right
  there, the person simply may not change it.
"""

from config.errors import Codes, api_denied
from rest_framework import viewsets
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated


def user_school_id(user):
    """The school of a signed-in user, or None for everybody else."""
    if user is None or not user.is_authenticated:
        return None
    return user.school_id


class IsSchoolMember(BasePermission):
    """
    Signed in and attached to a school.

    A user with no school is a real, valid state — invited by nobody yet — so
    the answer names it with a code instead of a bare 403: the interface shows
    "ask your administrator" rather than a dead end.
    """

    def has_permission(self, request, view):
        if user_school_id(request.user) is None:
            api_denied(
                Codes.NO_SCHOOL,
                "You do not belong to any school yet.",
            )
        return True


class IsTeacher(BasePermission):
    """
    Учитель, а не ученик. Стоит рядом с `IsSchoolMember`, а не вместо него.

    Разделены нарочно: школы у человека может ещё не быть (никто не
    пригласил), и учительские экраны обязаны это состояние объяснять, а не
    отказывать. Вид же известен всегда, поэтому проверка вида отдельная и
    применима там, где школа необязательна — например к статусу первого
    входа.

    Ученику отвечаем 403 с кодом, а не 404: он законный пользователь этой
    школы, просто раздел не его. Прятать существование учительских разделов
    смысла нет — про них он и так знает.
    """

    def has_permission(self, request, view):
        if getattr(request.user, "is_student", False):
            api_denied(
                Codes.TEACHERS_ONLY,
                "This section is for teachers.",
            )
        return True


class IsStudent(BasePermission):
    """Зеркало `IsTeacher`: разделы ученика учителю тоже незачем."""

    def has_permission(self, request, view):
        if not getattr(request.user, "is_student", False):
            api_denied(
                Codes.STUDENTS_ONLY,
                "This section is for students.",
            )
        return True


class IsSchoolAdminForWrite(BasePermission):
    """Reading is for every member of the school, writing for its admins."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        if not request.user.is_school_admin:
            api_denied(
                Codes.SCHOOL_ADMIN_REQUIRED,
                "Only a school administrator can change this.",
            )
        return True


class IsSchoolAdmin(BasePermission):
    """The administrator role, whatever the method — reading included."""

    def has_permission(self, request, view):
        if not request.user.is_school_admin:
            api_denied(
                Codes.SCHOOL_ADMIN_REQUIRED,
                "Only a school administrator can see this.",
            )
        return True


class IsSuperuser(BasePermission):
    """
    The one place where being a Django superuser means something in the app.

    Everywhere else a superuser is an ordinary member of their school — the
    role that governs a school lives on the school, not on the account. But
    somebody has to create the schools themselves, and that cannot come from
    inside a school that does not exist yet.
    """

    def has_permission(self, request, view):
        if not request.user.is_superuser:
            api_denied(
                Codes.SUPERUSER_REQUIRED,
                "Only a superuser can manage the list of schools.",
            )
        return True


class SchoolScopedViewSet(viewsets.ModelViewSet):
    """
    A school object: everybody in the school reads it, admins change it.

    `school_path` is the ORM path from this model to the school — "school"
    for the ones holding the key themselves, "year__school" for the calendar
    markup hanging off a year.
    """

    school_path = "school"
    permission_classes = [
        IsAuthenticated,
        IsSchoolMember,
        IsTeacher,
        IsSchoolAdminForWrite,
    ]

    def get_queryset(self):
        # the filter closes reading and writing at once: an object from
        # another school is simply not found, on any action including detail
        return super().get_queryset().filter(
            **{self.school_path: self.request.user.school_id}
        )


def require_course_teacher(user, course):
    """
    Правит план тот, кого на курс назначили, — и только он.

    Отдельной функцией, потому что спрашивают это из двух мест: из вьюсета
    плана и из «взять шаблон с полки» в библиотеке, которая пишет в тот же
    план мимо него.
    """
    from schedule.models import CourseAssignment

    if not CourseAssignment.objects.filter(course=course, teacher=user).exists():
        api_denied(
            Codes.NOT_COURSE_TEACHER,
            "Only the teacher assigned to this course can change its plan.",
        )


class CourseScopedViewSet(viewsets.ModelViewSet):
    """
    Объект курса: читает тот, кто в курсе работает, пишет ведущий учитель.

    Четвёртая форма доступа, и появилась она вместе с правилом «ведущий
    учитель у курса один». Так устроены учебный план и работы: пока план
    был личным, у одного курса могло оказаться два плана — свой у каждого
    ведущего, — а смена ведущего оставляла программу висеть на том, кто
    ушёл; у работ смена ведущего оставляла непроверенное без хозяина.

    Читают все, кто в курсе работает (`Course.objects.for_teacher`):
    назначенный плюс тот, у кого в курсе остались уроки — назначение
    снимают, а расписание остаётся, и прятать от человека программу курса,
    в котором он ещё ведёт занятия, незачем.

    Пишет только назначенный: иначе один и тот же план правили бы двое, и
    мы вернулись бы туда, откуда ушли.

    `course_path` — путь до курса, как `school_path` у школьных объектов:
    у работы это `"course"`, у задачи внутри работы `"work__course"`, у
    отправки `"task__work__course"`.
    """

    course_path = "course"
    permission_classes = [IsAuthenticated, IsSchoolMember, IsTeacher]

    def my_courses(self):
        from schedule.models import Course

        return Course.objects.for_teacher(self.request.user)

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(**{f"{self.course_path}__in": self.my_courses()})
        )

    def require_lead(self, course):
        require_course_teacher(self.request.user, course)

    def course_of(self, obj):
        for step in self.course_path.split("__"):
            obj = getattr(obj, step)
        return obj

    def get_object(self):
        obj = super().get_object()
        if self.request.method not in SAFE_METHODS:
            self.require_lead(self.course_of(obj))
        return obj

    def perform_create(self, serializer):
        # право спрашивается **до** записи: у вложенного объекта курса в теле
        # нет, но есть родитель — по нему и доходим. Проверить после save()
        # было бы дешевле и неверно: запросы не атомарны, и отклонённая
        # строка осталась бы в базе
        steps = self.course_path.split("__")
        target = serializer.validated_data[steps[0]]
        for step in steps[1:]:
            target = getattr(target, step)

        self.require_lead(target)
        serializer.save()


class TeacherScopedViewSet(viewsets.ModelViewSet):
    """
    A personal object: only its own teacher, and only inside their school.

    The role means nothing here — an administrator is a teacher with extra
    rights over the school's shared objects, not over other people's lessons.
    """

    teacher_path = "teacher"
    permission_classes = [IsAuthenticated, IsSchoolMember, IsTeacher]

    def get_queryset(self):
        return super().get_queryset().filter(**{self.teacher_path: self.request.user})
