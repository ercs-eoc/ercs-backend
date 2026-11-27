import typing

import strawberry
import strawberry_django
from django.core.files.storage import FileSystemStorage, default_storage
from django.db.models.fields.files import FileField, ImageField
from strawberry.types import Info
from strawberry_django.fields.types import field_type_map

from utils.file_types import guess_content_type

ResultTypeVar = typing.TypeVar("ResultTypeVar")

CustomErrorType = strawberry.scalar(
    typing.NewType("CustomErrorType", object),
    description="A generic type to return error messages",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)


@strawberry.type
class MutationResponseType(typing.Generic[ResultTypeVar]):  # noqa: UP046
    ok: bool = True
    errors: CustomErrorType | None = None
    result: ResultTypeVar | None = None


@strawberry.type
class DeleteMutationResponseType:
    """Outcome of a delete: it succeeded, or it did not and here is why.

    Deletes carry no `result` -- the object is gone, and returning a Django type the
    client cannot use only risks resolving its fields in an async context.
    """

    ok: bool = True
    errors: CustomErrorType | None = None


@strawberry.type
class DjangoFileType:
    name: str
    size: int

    @strawberry_django.field
    def url(
        self,
        info: Info,
        file: strawberry.Parent[typing.Any],
    ) -> str:
        if isinstance(default_storage, FileSystemStorage):
            return info.context.request.build_absolute_uri(file.url)
        return file.url

    @strawberry_django.field
    def content_type(
        self,
        file: strawberry.Parent[typing.Any],
    ) -> str | None:
        return guess_content_type(file.name)


field_type_map.update(
    {
        FileField: DjangoFileType,
        ImageField: DjangoFileType,
    },
)
