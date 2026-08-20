from django.urls import path

from .views import (
    ProblemView,
    SavedSearchView,
    SavedSearchesView,
    SearchView,
    SolutionsView,
    SourceView,
    SourcesView,
    TagLinkView,
    TagsView,
)

urlpatterns = [
    path("sources/", SourcesView.as_view(), name="bank-sources"),
    path("sources/<int:pk>/", SourceView.as_view(), name="bank-source"),
    path("problems/<int:pk>/", ProblemView.as_view(), name="bank-problem"),
    path("solutions/", SolutionsView.as_view(), name="bank-solutions"),
    path("search/", SearchView.as_view(), name="bank-search"),
    path("searches/", SavedSearchesView.as_view(), name="bank-searches"),
    path("searches/<int:pk>/", SavedSearchView.as_view(), name="bank-saved-search"),
    path("tags/", TagsView.as_view(), name="bank-tags"),
    path("tag-links/", TagLinkView.as_view(), name="bank-tag-links"),
]
