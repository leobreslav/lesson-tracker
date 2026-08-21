from django.urls import path

from .views import (
    AnalogueView,
    ImportView,
    ChronologyView,
    CopyView,
    ProblemView,
    SearchView,
    SolutionsView,
    SourceView,
    SourcesView,
    TagLinkView,
    TagsView,
    TopicView,
    TopicsView,
)

urlpatterns = [
    path("sources/", SourcesView.as_view(), name="bank-sources"),
    path("sources/<int:pk>/", SourceView.as_view(), name="bank-source"),
    path("problems/<int:pk>/", ProblemView.as_view(), name="bank-problem"),
    path("sources/<int:pk>/import/", ImportView.as_view(), name="bank-import"),
    path("solutions/", SolutionsView.as_view(), name="bank-solutions"),
    path("search/", SearchView.as_view(), name="bank-search"),
    path("copy/", CopyView.as_view(), name="bank-copy"),
    path("analogues/", AnalogueView.as_view(), name="bank-analogues"),
    path("topics/", TopicsView.as_view(), name="bank-topics"),
    path("topics/<int:pk>/", TopicView.as_view(), name="bank-topic"),
    path("chronology/<int:course>/", ChronologyView.as_view(), name="bank-chronology"),
    path("tags/", TagsView.as_view(), name="bank-tags"),
    path("tag-links/", TagLinkView.as_view(), name="bank-tag-links"),
]
