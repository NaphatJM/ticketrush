"""Base views. Every endpoint subclasses these, never `rest_framework` directly.

Every response has one shape: `{"status": {"code": ..., "message": ...}, "data": ...}`.
"""

from typing import TypedDict

from rest_framework import status
from rest_framework.generics import CreateAPIView as BaseCreateAPIView
from rest_framework.generics import ListAPIView as BaseListAPIView
from rest_framework.generics import ListCreateAPIView as BaseListCreateAPIView
from rest_framework.generics import RetrieveAPIView as BaseRetrieveAPIView
from rest_framework.generics import RetrieveUpdateAPIView as BaseRetrieveUpdateAPIView
from rest_framework.generics import RetrieveUpdateDestroyAPIView as BaseRetrieveUpdateDestroyAPIView
from rest_framework.generics import UpdateAPIView as BaseUpdateAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView as BaseAPIView

from rest_framework_tracking.mixins import TrackingMixin

from .constants import CODE_SUCCESS
from .constants import MESSAGE_SUCCESS
from .logging import LoggingMixin


class StandardResponseStatus(TypedDict):
    code: str
    message: str


class StandardResponse[T](TypedDict):
    status: StandardResponseStatus
    data: T


def encapsulation_result[T](data: T, status_code: str = CODE_SUCCESS, status_message: str = MESSAGE_SUCCESS) -> StandardResponse[T]:
    return StandardResponse(status=StandardResponseStatus(code=status_code, message=status_message), data=data)


class EnvelopeMixin:
    def encap_success_overhead[T](self, data: T) -> StandardResponse[T]:
        return encapsulation_result(data)


class APIView(EnvelopeMixin, TrackingMixin, LoggingMixin, BaseAPIView):
    pass


class CreateAPIView(EnvelopeMixin, TrackingMixin, LoggingMixin, BaseCreateAPIView):
    def create(self, request: Request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(encapsulation_result(serializer.data), status=status.HTTP_201_CREATED, headers=headers)


class UpdateAPIView(EnvelopeMixin, TrackingMixin, LoggingMixin, BaseUpdateAPIView):
    def update(self, request: Request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        if getattr(instance, '_prefetched_objects_cache', None):
            instance._prefetched_objects_cache = {}
        return Response(encapsulation_result(serializer.data))


class RetrieveAPIView(EnvelopeMixin, TrackingMixin, LoggingMixin, BaseRetrieveAPIView):
    def retrieve(self, request: Request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object())
        return Response(encapsulation_result(serializer.data))


class ListAPIView(EnvelopeMixin, TrackingMixin, LoggingMixin, BaseListAPIView):
    def list(self, request: Request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(encapsulation_result(serializer.data))


class ListCreateAPIView(EnvelopeMixin, TrackingMixin, LoggingMixin, BaseListCreateAPIView):
    list = ListAPIView.__dict__['list']
    create = CreateAPIView.__dict__['create']


class RetrieveUpdateAPIView(EnvelopeMixin, TrackingMixin, LoggingMixin, BaseRetrieveUpdateAPIView):
    retrieve = RetrieveAPIView.__dict__['retrieve']
    update = UpdateAPIView.__dict__['update']


class RetrieveUpdateDestroyAPIView(EnvelopeMixin, TrackingMixin, LoggingMixin, BaseRetrieveUpdateDestroyAPIView):
    retrieve = RetrieveAPIView.__dict__['retrieve']
    update = UpdateAPIView.__dict__['update']

    def destroy(self, request: Request, *args, **kwargs):
        """Returns 200 with the deleted object's last state, not 204, so the envelope is always present."""
        instance = self.get_object()
        data = self.get_serializer(instance).data
        self.perform_destroy(instance)
        return Response(encapsulation_result(data))
