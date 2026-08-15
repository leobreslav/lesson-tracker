from rest_framework.routers import DefaultRouter

from .views import CourseViewSet, LessonViewSet

router = DefaultRouter()
router.register("courses", CourseViewSet, basename="course")
router.register("lessons", LessonViewSet, basename="lesson")

urlpatterns = router.urls
