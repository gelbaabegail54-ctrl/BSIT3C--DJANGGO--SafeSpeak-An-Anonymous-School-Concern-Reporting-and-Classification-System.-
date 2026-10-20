from django.urls import path
from . import views

urlpatterns = [
    path('', views.login_view, name='login'),
    path('home/', views.home, name='dashboard'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    path('submit/', views.submit_concern, name='submit_concern'),
    path('confess/', views.submit_confession, name='submit_confession'),
    path('reports/<str:kind>/<int:pk>/comment/', views.add_comment, name='add_comment'),
    path('comments/<int:pk>/edit/', views.edit_comment, name='edit_comment'),
    path('comments/<int:pk>/delete/', views.delete_comment, name='delete_comment'),
    path('admin/dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('admin/reports/<str:kind>/<int:pk>/', views.admin_report_detail, name='admin_report_detail'),
    path('admin/concerns/<int:pk>/status/', views.admin_update_status, name='admin_update_status'),
    path('admin/confessions/<int:pk>/status/', views.admin_update_confession_status, name='admin_update_confession_status'),
    path('admin/concerns/<int:pk>/response/', views.admin_add_concern_response, name='admin_add_concern_response'),
    path('admin/confessions/<int:pk>/response/', views.admin_add_confession_response, name='admin_add_confession_response'),
]