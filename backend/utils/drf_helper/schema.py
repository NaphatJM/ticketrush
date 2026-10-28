from drf_spectacular.utils import OpenApiResponse
from drf_spectacular.utils import inline_serializer
from rest_framework import serializers


def _status_field() -> serializers.Serializer:
    return inline_serializer(
        name='ResponseStatus',
        fields={
            'code': serializers.CharField(help_text='Machine-readable outcome; clients switch on this, not on the HTTP status.'),
            'message': serializers.CharField(help_text='Human-readable message.'),
        },
    )


def wrap_success(name: str, serializer: serializers.BaseSerializer) -> serializers.Serializer:
    return inline_serializer(name=f'{name}Success', fields={'status': _status_field(), 'data': serializer})


ERROR_RESPONSE = OpenApiResponse(
    response=inline_serializer(
        name='ErrorResponse',
        fields={'status': _status_field(), 'trace': serializers.DictField()},
    ),
    description='Every failure uses this shape; `status.code` identifies the cause.',
)
