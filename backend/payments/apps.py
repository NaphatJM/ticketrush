from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    name = 'payments'

    def ready(self) -> None:
        from .gateways import check_configuration  # noqa: PLC0415 -- adapters import models, so the app registry must be ready

        check_configuration()
