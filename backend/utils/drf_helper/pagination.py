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
