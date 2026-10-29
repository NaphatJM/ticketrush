from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from rest_framework_simplejwt.token_blacklist.admin import OutstandingTokenAdmin
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

from .models import User


@admin.register(User)
class TicketRushUserAdmin(UserAdmin):
    fieldsets = (*UserAdmin.fieldsets, ('Role', {'fields': ('role',)}))
    list_display = (*UserAdmin.list_display, 'role')
    list_filter = (*UserAdmin.list_filter, 'role')


admin.site.unregister(OutstandingToken)


@admin.register(OutstandingToken)
class RedactedOutstandingTokenAdmin(OutstandingTokenAdmin):
    """A stored refresh token is a working credential, so the admin never shows it."""

    exclude = ('token',)

    def get_readonly_fields(self, *args, **kwargs) -> list[str]:
        return [name for name in super().get_readonly_fields(*args, **kwargs) if name != 'token']
