import strawberry
import strawberry_django
from strawberry_django.pagination import OffsetPaginated

from main.graphql.permissions import IsAuthenticated

from .filters import GalleryAlbumFilter, GalleryImageFilter
from .orders import GalleryAlbumOrder, GalleryImageOrder
from .types import GalleryAlbumType, GalleryImageType


@strawberry.type
class Query:
    gallery_albums: OffsetPaginated[GalleryAlbumType] = strawberry_django.offset_paginated(
        filters=GalleryAlbumFilter,
        ordering=GalleryAlbumOrder,
        permission_classes=[IsAuthenticated],
    )

    gallery_album: GalleryAlbumType = strawberry_django.field(
        permission_classes=[IsAuthenticated],
    )

    gallery_images: OffsetPaginated[GalleryImageType] = strawberry_django.offset_paginated(
        filters=GalleryImageFilter,
        ordering=GalleryImageOrder,
        permission_classes=[IsAuthenticated],
    )
