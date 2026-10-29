from django.urls import path

from . import views


urlpatterns = [
    path('holds/<uuid:uuid>/checkout/', views.CheckoutView.as_view(), name='hold-checkout'),
    path('orders/<uuid:uuid>/', views.OrderDetailView.as_view(), name='order-detail'),
    path('me/orders/', views.MyOrdersView.as_view(), name='my-orders'),
    path('me/tickets/', views.MyTicketsView.as_view(), name='my-tickets'),
    path('webhooks/<slug:provider>/', views.WebhookView.as_view(), name='webhook'),
]
