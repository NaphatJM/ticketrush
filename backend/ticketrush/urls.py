from django.conf import settings
from django.contrib import admin
from django.urls import include
from django.urls import path
from drf_spectacular.views import SpectacularAPIView
from drf_spectacular.views import SpectacularSwaggerView

from . import views


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('accounts.urls')),
    path('api/', include('ticketing.urls')),
    path('api/', include('payments.urls')),
    path('system/healthcheck/', views.healthcheck, name='healthcheck'),
    path('system/readiness/', views.readiness, name='readiness'),
    path('system/dependencies/', views.dependencies, name='dependencies'),
    path('system/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('system/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='docs'),
]

if settings.PAYMENT_GATEWAY == 'mock':
    urlpatterns.append(path('mock-gateway/', include('mockgateway.urls')))
