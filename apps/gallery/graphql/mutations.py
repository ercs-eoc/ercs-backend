from collections import Counter

import strawberry
import strawberry_django
from django.db.models import Count

from apps.gallery.models import GalleryAlbum, GalleryImage
from apps.gallery.serializers import (
    GalleryAlbumSerializer,
    GalleryAlbumUpdateSerializer,
    GalleryImageSerializer,
)
from main.graphql.context import Info
from main.graphql.permissions import IsAuthenticatedDelete, IsAuthenticatedMutation
from utils.graphql.drf import MutationCustomErrorType
from utils.graphql.mutations import ModelMutation, handle_delete_mutation
from utils.graphql.types import DeleteMutationResponseType, MutationResponseType

from .inputs import GalleryAlbumCreateInput, GalleryAlbumUpdateInput, GalleryImageBulkCreateInput
from .types import GalleryAlbumType, GalleryImageType

MAX_BULK_GALLERY_IMAGES = 100
MAX_GALLERY_ALBUM_IMAGES = 100


@strawberry.type
class Mutation:
    @strawberry_django.mutation(permission_classes=[IsAuthenticatedMutation])
    async def create_gallery_album(
        self,
        info: Info,
        data: GalleryAlbumCreateInput,
    ) -> MutationResponseType[GalleryAlbumType]:
        return await ModelMutation(GalleryAlbumSerializer).handle_create_mutation(data, info)

    @strawberry_django.mutation(permission_classes=[IsAuthenticatedMutation])
    async def update_gallery_album(
        self,
        info: Info,
        id: strawberry.ID,
        data: GalleryAlbumUpdateInput,
    ) -> MutationResponseType[GalleryAlbumType]:
        instance = await GalleryAlbum.objects.aget(id=id)
        return await ModelMutation(GalleryAlbumUpdateSerializer).handle_update_mutation(data, info, instance)

    @strawberry_django.mutation(permission_classes=[IsAuthenticatedMutation])
    async def bulk_create_gallery_images(
        self,
        info: Info,
        data: GalleryImageBulkCreateInput,
    ) -> MutationResponseType[list[GalleryImageType]]:
        if not data.images:
            return MutationResponseType(
                ok=False,
                errors=MutationCustomErrorType.generate_message("Add at least one image to upload."),
            )
        if len(data.images) > MAX_BULK_GALLERY_IMAGES:
            return MutationResponseType(
                ok=False,
                errors=MutationCustomErrorType.generate_message(
                    f"You can upload up to {MAX_BULK_GALLERY_IMAGES} images at a time.",
                ),
            )
        incoming_counts = Counter(str(image.album) for image in data.images)
        existing_counts = {
            str(album_id): count
            async for album_id, count in GalleryImage.objects.filter(album_id__in=incoming_counts.keys())
            .values("album_id")
            .annotate(count=Count("id"))
            .values_list("album_id", "count")
        }
        for album_id, incoming in incoming_counts.items():
            if existing_counts.get(album_id, 0) + incoming > MAX_GALLERY_ALBUM_IMAGES:
                return MutationResponseType(
                    ok=False,
                    errors=MutationCustomErrorType.generate_message(
                        f"An album can have at most {MAX_GALLERY_ALBUM_IMAGES} images.",
                    ),
                )
        return await ModelMutation(GalleryImageSerializer).handle_bulk_create_mutation(data.images, info)

    @strawberry_django.mutation(permission_classes=[IsAuthenticatedDelete], handle_django_errors=False)
    async def delete_gallery_image(
        self,
        info: Info,
        id: strawberry.ID,
    ) -> DeleteMutationResponseType:
        return await handle_delete_mutation(GalleryImage, id=id)

    @strawberry_django.mutation(permission_classes=[IsAuthenticatedDelete], handle_django_errors=False)
    async def delete_gallery_album(
        self,
        info: Info,
        id: strawberry.ID,
    ) -> DeleteMutationResponseType:
        return await handle_delete_mutation(GalleryAlbum, id=id)
