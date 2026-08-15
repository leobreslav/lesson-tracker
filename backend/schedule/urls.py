from rest_framework.routers import DefaultRouter

from .views import CourseViewSet, SlotViewSet

router = DefaultRouter()
router.register("courses", CourseViewSet, basename="course")
router.register("slots", SlotViewSet, basename="slot")

urlpatterns = router.urls
