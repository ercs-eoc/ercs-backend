import strawberry
from strawberry.file_uploads import Upload


@strawberry.input
class GalleryAlbumCreateInput:
    title: str
    description: str | None = strawberry.UNSET


@strawberry.input
class GalleryAlbumUpdateInput:
    title: str | None = strawberry.UNSET
    description: str | None = strawberry.UNSET
    cover_image: strawberry.ID | None = strawberry.UNSET


@strawberry.input
class GalleryImageCreateInput:
    album: strawberry.ID
    image: Upload
    caption: str | None = strawberry.UNSET
    order: int = 0


@strawberry.input
class GalleryImageBulkCreateInput:
    images: list[GalleryImageCreateInput]
