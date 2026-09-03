from rest_framework.pagination import PageNumberPagination
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
import math

class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_response(self, data):
        total_items = self.page.paginator.count
        page_size = self.get_page_size(self.request)
        total_pages = math.ceil(total_items / page_size)

        return Response({
            "count": total_items,
            "total_pages": total_pages,
            "current_page": self.page.number,
            "next": self.get_next_link(),
            "previous": self.get_previous_link(),
            "results": data
        })
