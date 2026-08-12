from rest_framework.routers import DefaultRouter

from .views import CourseViewSet, LessonSlotViewSet

router = DefaultRouter()
router.register("courses", CourseViewSet, basename="course")
router.register("slots", LessonSlotViewSet, basename="lessonslot")

urlpatterns = router.urls
