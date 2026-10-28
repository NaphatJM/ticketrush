from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        BUYER = 'buyer'
        ORGANIZER = 'organizer'

    role = models.CharField(max_length=16, choices=Role.choices, default=Role.BUYER)
