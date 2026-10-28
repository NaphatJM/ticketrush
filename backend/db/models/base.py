from django.db import models
from django.utils.translation import gettext_lazy as _

from db.utils import uuid7


class BaseModel(models.Model):
    """`id` stays the internal key; `uuid` is the only identifier exposed through the API."""

    uuid = models.UUIDField(_('UUID'), default=uuid7, unique=True, editable=False)
    created_on = models.DateTimeField(_('created on'), auto_now_add=True, db_index=True)
    updated_on = models.DateTimeField(_('updated on'), auto_now=True, db_index=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        # auto_now is skipped when update_fields omits the field.
        update_fields = kwargs.get('update_fields')
        if update_fields is not None:
            kwargs['update_fields'] = {*update_fields, 'updated_on'}
        super().save(*args, **kwargs)
