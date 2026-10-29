from django.contrib import admin
from django.contrib import messages
from django.db import transaction
from django.utils import timezone

from audit.constants import ActivityVerb
from audit.services import log_action

from .models import DeadLetter
from .models import IdempotencyRecord
from .models import OutboxMessage
from .outbox import task_by_name


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


@admin.register(IdempotencyRecord)
class IdempotencyRecordAdmin(ReadOnlyAdmin):
    list_display = ('created_on', 'endpoint', 'user', 'key', 'state', 'response_status', 'expires_at')
    list_filter = ('endpoint', 'state')
    search_fields = ('key',)
    list_select_related = ('user',)


@admin.register(OutboxMessage)
class OutboxMessageAdmin(ReadOnlyAdmin):
    list_display = ('id', 'topic', 'created_on', 'published_at', 'attempts', 'last_error')
    list_filter = ('topic', ('published_at', admin.EmptyFieldListFilter))


@admin.register(DeadLetter)
class DeadLetterAdmin(ReadOnlyAdmin):
    list_display = ('failed_at', 'task_name', 'error', 'replayed_at')
    list_filter = ('task_name', ('replayed_at', admin.EmptyFieldListFilter))
    actions = ('replay',)

    @admin.action(description='Replay the selected dead letters')
    def replay(self, request, queryset):
        replayed = 0
        for letter in queryset.filter(replayed_at__isnull=True):
            with transaction.atomic():
                DeadLetter.objects.filter(pk=letter.pk).update(replayed_at=timezone.now())
                log_action(ActivityVerb.DEAD_LETTER_REPLAYED, actor=request.user, target=letter, detail={'task': letter.task_name})
                transaction.on_commit(lambda letter=letter: task_by_name(letter.task_name).apply_async(kwargs=letter.args))
            replayed += 1
        self.message_user(request, f'Replayed {replayed} dead letter(s).', messages.SUCCESS)
