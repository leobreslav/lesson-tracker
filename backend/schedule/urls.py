from rest_framework.routers import DefaultRouter

from .views import (
    CourseViewSet,
    HomegroupStudentViewSet,
    HomegroupViewSet,
    RoomViewSet,
    SlotViewSet,
)

router = DefaultRouter()
router.register("courses", CourseViewSet, basename="course")
# кабинеты — справочник школы, но живёт он тут, рядом с расписанием:
# нужен он расписанию, и школьный раздел его только ведёт
router.register("rooms", RoomViewSet, basename="room")
# классы (хоумрумы) и их состав: связи с курсом у класса нет — класс курса
# выводится из его учеников, см. `Homegroup` в моделях
router.register("homegroups", HomegroupViewSet, basename="homegroup")
router.register(
    "homegroup-students", HomegroupStudentViewSet, basename="homegroup-student"
)
router.register("slots", SlotViewSet, basename="slot")

urlpatterns = router.urls
