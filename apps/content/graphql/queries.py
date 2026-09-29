import strawberry
import strawberry_django
from strawberry_django.pagination import OffsetPaginated

from .filters import NewsPostFilter
from .orders import NewsPostOrder
from .types import NewsPostType


@strawberry.type
class Query:
    news_posts: OffsetPaginated[NewsPostType] = strawberry_django.offset_paginated(
        filters=NewsPostFilter,
        ordering=NewsPostOrder,
    )

    news_post: NewsPostType = strawberry_django.field()
