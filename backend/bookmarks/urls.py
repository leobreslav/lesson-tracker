from rest_framework.routers import DefaultRouter

from .views import BookmarkFolderViewSet

router = DefaultRouter()
router.register("folders", BookmarkFolderViewSet, basename="bookmark-folder")

urlpatterns = router.urls
