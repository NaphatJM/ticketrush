from django.urls import path

from . import views


urlpatterns = [
    path('events/', views.EventListView.as_view(), name='event-list'),
    path('events/<uuid:uuid>/', views.EventDetailView.as_view(), name='event-detail'),
    path('events/<uuid:uuid>/holds/', views.HoldCreateView.as_view(), name='hold-create'),
    path('holds/<uuid:uuid>/', views.HoldReleaseView.as_view(), name='hold-release'),
]
