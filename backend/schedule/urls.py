from rest_framework.routers import DefaultRouter

from .views import LessonSlotViewSet, SchoolClassViewSet

router = DefaultRouter()
router.register("classes", SchoolClassViewSet, basename="schoolclass")
router.register("slots", LessonSlotViewSet, basename="lessonslot")

urlpatterns = router.urls
