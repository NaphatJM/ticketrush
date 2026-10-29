from django.urls import path

from . import views


urlpatterns = [
    path('charges/<str:charge_id>/', views.ChargeDetailView.as_view(), name='mock-charge-detail'),
    path('charges/<str:charge_id>/pay/', views.ChargePayView.as_view(), name='mock-charge-pay'),
]
