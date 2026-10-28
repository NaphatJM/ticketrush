from django.contrib import admin
from django.urls import path
from drf_spectacular.views import SpectacularAPIView
from drf_spectacular.views import SpectacularSwaggerView

from . import views


urlpatterns = [
    path('staff-admin/', admin.site.urls),
    path('system/healthcheck/', views.healthcheck, name='healthcheck'),
    path('system/readiness/', views.readiness, name='readiness'),
    path('system/dependencies/', views.dependencies, name='dependencies'),
    path('system/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('system/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='docs'),
]
