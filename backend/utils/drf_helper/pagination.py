from rest_framework.pagination import PageNumberPagination as BasePageNumberPagination
from rest_framework.response import Response

from .constants import CODE_SUCCESS
from .constants import MESSAGE_SUCCESS


class PageNumberPagination(BasePageNumberPagination):
    page_size_query_param = 'page_size'
    max_page_size = 200

    def get_paginated_response(self, data) -> Response:
        return Response(
            {
                'status': {'code': CODE_SUCCESS, 'message': MESSAGE_SUCCESS},
                'links': {'next': self.get_next_link(), 'previous': self.get_previous_link()},
                'count': self.page.paginator.count,
                'data': data,
            }
        )

    def get_paginated_response_schema(self, schema: dict) -> dict:
        link = {'type': 'string', 'format': 'uri', 'nullable': True}
        return {
            'type': 'object',
            'required': ['status', 'links', 'count', 'data'],
            'properties': {
                'status': {
                    'type': 'object',
                    'required': ['code', 'message'],
                    'properties': {'code': {'type': 'string', 'example': CODE_SUCCESS}, 'message': {'type': 'string'}},
                },
                'links': {'type': 'object', 'required': ['next', 'previous'], 'properties': {'next': link, 'previous': link}},
                'count': {'type': 'integer'},
                'data': schema,
            },
        }
