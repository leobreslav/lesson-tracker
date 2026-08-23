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
3. объект курса — и читает, и пишет его назначенный ведущий учитель. Так
   устроены учебный план и работы;
4. расписание — читает вся школа, пишет ведущий курса **или**
   администратор. Единственный объект такой формы, и форма у него такая
   потому, что расписание одновременно и общий артефакт школы (по нему
   живут все), и содержимое курса (его правит тот, кто курс ведёт).

Личной формы больше нет. Она была, и держалась на том, что курс могут
вести двое: тогда расписание, план и работы законно различались у двух
человек внутри одного курса. Ведущий стал один, различаться перестало
нечему, и всё, что лежит внутри курса, переехало на курс — вместе с тем,
что смену ведущего оно теперь переживает целиком.

Every viewset picks a base class below and says which ORM path leads from its
model to the school (``school_path``) or to the course (``course_path``).
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
    Учитель — по виду, а не «все, кто не ученик». Стоит рядом с
    `IsSchoolMember`, а не вместо него.

    Разделены нарочно: школы у человека может ещё не быть (никто не
    пригласил), и учительские экраны обязаны это состояние объяснять, а не
    отказывать. Вид же известен всегда, поэтому проверка вида отдельная и
    применима там, где школа необязательна — например к статусу первого
    входа.

    **Проверка спрашивает вид прямо, и это не придирка.** Пока видов было два,
    она читала «не ученик», и это совпадало с «учитель». Родитель совпадение
    сломал: он не ученик — и по прежнему правилу прошёл бы в учебный план,
    расписание и работы всей школы. Ошибка при этом была бы молчаливой:
    ни один существующий тест не покраснел бы, потому что все они спрашивают
    про ученика. Теперь добавление вида ничего не открывает само.

    Не своему отвечаем 403 с кодом, а не 404: он законный пользователь этой
    школы, просто раздел не его. Прятать существование учительских разделов
    смысла нет — про них он и так знает.
    """

    def has_permission(self, request, view):
        if not getattr(request.user, "is_teacher", False):
            api_denied(
                Codes.TEACHERS_ONLY,
                "This section is for teachers.",
            )
        return True


class IsStudent(BasePermission):
    """Зеркало `IsTeacher`: разделы ученика ни учителю, ни родителю незачем."""

    def has_permission(self, request, view):
        if not getattr(request.user, "is_student", False):
            api_denied(
                Codes.STUDENTS_ONLY,
                "This section is for students.",
            )
        return True


class IsParent(BasePermission):
    """Разделы родителя: свой разговор с учителем и выбор ребёнка."""

    def has_permission(self, request, view):
        if not getattr(request.user, "is_parent", False):
            api_denied(
                Codes.PARENTS_ONLY,
                "This section is for parents.",
            )
        return True


class IsParentOrTeacher(BasePermission):
    """
    Две стороны разговора о ребёнке. Ученик в него не входит.

    Класс на пару видов, а не проверка внутри вьюхи: «мои разговоры» — один
    вопрос для родителя и для учителя, и отвечает на него участие в треде, а
    не вид. Разведи это на две вьюхи — и они разойдутся в первой же правке,
    как уже расходились выборки курсов.
    """

    def has_permission(self, request, view):
        user = request.user
        if not (
            getattr(user, "is_parent", False) or getattr(user, "is_teacher", False)
        ):
            api_denied(
                Codes.PARENTS_ONLY,
                "This section is for parents and teachers.",
            )
        return True


class IsFamily(BasePermission):
    """
    Ученик или его родитель — те, кому показывают ученическое.

    Отдельный класс, а не `IsStudent | IsParent`: вопрос «кому этот раздел»
    задаётся в одном месте, и ответ на него читается словом, а не выражением.
    **Чьи именно данные показывать — вопрос другой**, и отвечает на него
    `families.viewing.subject_of`: у ученика это он сам, у родителя — названный
    ребёнок, и чужой ребёнок для него не существует.
    """

    def has_permission(self, request, view):
        if not getattr(request.user, "is_family", False):
            api_denied(
                Codes.STUDENTS_ONLY,
                "This section is for students and their parents.",
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
                # не «список школ»: разделов у суперпользователя два —
                # школы и обращения пользователей, — и отказ, называющий
                # один из них, на втором отправляет искать не там
                "This section is for superusers.",
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


class IsCourseTeacherOrSchoolAdmin(BasePermission):
    """
    Расписание: читает вся школа, пишет ведущий курса или администратор.

    Проверка объектная, потому что «можно ли писать» зависит от курса, а не
    от человека вообще: свой курс учитель правит целиком, чужой не трогает.
    Администратор правит любой — расписание школы составляет он, и чинить
    сломанную неделю тоже ему.
    """

    def has_permission(self, request, view):
        return True

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return allowed_to_write_schedule(request.user, obj.course)


def allowed_to_write_schedule(user, course) -> bool:
    from schedule.models import CourseAssignment

    if user.is_school_admin and course.school_id == user.school_id:
        return True

    return CourseAssignment.objects.filter(course=course, teacher=user).exists()


def require_schedule_write(user, course):
    """Тот же вопрос там, где объекта на входе нет: курс приходит в теле."""
    if not allowed_to_write_schedule(user, course):
        api_denied(
            Codes.NOT_COURSE_TEACHER,
            "Only the teacher of this course or a school administrator "
            "can change its schedule.",
        )


class CourseScopedViewSet(viewsets.ModelViewSet):
    """
    Объект курса: и читает, и пишет его ведущий учитель.

    Четвёртая форма доступа, и появилась она вместе с правилом «ведущий
    учитель у курса один». Так устроены учебный план, работы и расписание:
    всё это принадлежит курсу, а не человеку, и потому переживает смену
    ведущего целиком.

    Имя владельца лежит **не на объекте**, а в назначении на курс
    (`Course.objects.for_teacher`), и разница не косметическая: назначение
    можно снять, и тогда вся работа достаётся следующему ведущему, а не
    остаётся висеть на ушедшем. Была и третья форма — личный объект с полем
    `teacher` на нём самом, — и она ушла целиком: внутри курса личного
    больше нет.

    Читают и пишут одни и те же — назначенные. Какое-то время читать мог и
    тот, у кого в курсе остались уроки; это различие исчезло вместе с
    личным расписанием: «работаю в курсе» и «веду курс» стали одним и тем
    же утверждением.

    `course_path` — путь до курса, как `school_path` у школьных объектов:
    у работы это `"course"`, у задачи внутри работы `"work__course"`, у
    отправки `"task__work__course"`.
    """

    course_path = "course"
    permission_classes = [IsAuthenticated, IsSchoolMember, IsTeacher]

    def my_courses(self):
        """
        Курсы, в которых этому человеку можно работать.

        Ведущему — свои, администратору школы — все её: он чинит чужую
        неделю в расписании и правит журнал занятия с тех пор, как эти
        экраны появились, и держать план с работами закрытыми было
        непоследовательностью, а не принципом.

        Имя метода осталось прежним, а вот значение сузилось до «право»:
        «какие курсы показывать по умолчанию» отвечает `for_teacher`, и
        путать их нельзя — у завуча это разные списки.
        """
        from schedule.models import Course

        return Course.objects.writable_by(self.request.user)

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(**{f"{self.course_path}__in": self.my_courses()})
        )
