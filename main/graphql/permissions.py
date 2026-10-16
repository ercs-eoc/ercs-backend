import typing

from strawberry.permission import BasePermission
from strawberry.types import Info

from apps.users.models import UserRole
from utils.graphql.drf import MutationCustomErrorType
from utils.graphql.types import DeleteMutationResponseType, MutationResponseType

NOT_AUTHENTICATED_MESSAGE = "You need to be signed in to perform this action."


def _role_denied_message(roles: tuple[UserRole, ...]) -> str:
    labels = [str(role.label) for role in roles]
    joined = labels[0] if len(labels) == 1 else f"{', '.join(labels[:-1])} or {labels[-1]}"
    return f"You do not have permission to perform this action. Only {joined} users can do this."


class IsAuthenticated(BasePermission):
    """Reject anonymous callers.

    Used on query fields, where a denial is reported as a top-level GraphQL error.
    Mutations should use `IsAuthenticatedMutation` instead so the message reaches
    the mutation payload.
    """

    message = NOT_AUTHENTICATED_MESSAGE
    error_extensions = {"code": "NOT_AUTHENTICATED"}  # noqa: RUF012

    @typing.override
    def has_permission(self, source: typing.Any, info: Info, **_: typing.Any) -> bool:
        user = info.context.request.user
        return bool(user and user.is_authenticated)


class IsStaffOrAbove(BasePermission):
    """Allow staff and the two admin tiers; Partner and Viewer are read-only."""

    allowed_roles: typing.ClassVar[tuple[UserRole, ...]] = (
        UserRole.STAFF,
        UserRole.REGIONAL_ADMIN,
        UserRole.HQ_ADMIN,
    )
    message = _role_denied_message(allowed_roles)
    error_extensions = {"code": "PERMISSION_DENIED"}  # noqa: RUF012

    @typing.override
    def has_permission(self, source: typing.Any, info: Info, **_: typing.Any) -> bool:
        user = info.context.request.user
        if not (user and user.is_authenticated):
            return False
        return user.role in self.allowed_roles


class IsHQAdmin(BasePermission):
    """Allow only HQ admins."""

    allowed_roles: typing.ClassVar[tuple[UserRole, ...]] = (UserRole.HQ_ADMIN,)
    message = _role_denied_message(allowed_roles)
    error_extensions = {"code": "PERMISSION_DENIED"}  # noqa: RUF012

    @typing.override
    def has_permission(self, source: typing.Any, info: Info, **_: typing.Any) -> bool:
        user = info.context.request.user
        if not (user and user.is_authenticated):
            return False
        return user.role in self.allowed_roles


class MutationPermissionMixin:
    """Report a denial inside the mutation payload instead of raising.

    Strawberry's `PermissionExtension` wraps the field *outside* of
    `strawberry_django`'s error handling, so a raised permission error lands in the
    top-level `errors` array with `data` set to null. Clients read mutation failures
    off the payload's `errors`, so a raised error surfaces to them as an unexplained
    "something went wrong". Returning the response type instead keeps the message on
    the payload, where the rest of our validation errors already live.

    `response_type` must match the field's declared return type, since the value is
    handed straight back as the field's result.
    """

    response_type: typing.ClassVar[type] = MutationResponseType

    def on_unauthorized(self) -> typing.Any:
        message = getattr(self, "message", None) or NOT_AUTHENTICATED_MESSAGE
        return self.response_type(ok=False, errors=MutationCustomErrorType.generate_message(message))


class DeleteMutationPermissionMixin(MutationPermissionMixin):
    """Denial payload for delete fields, which return no `result`."""

    response_type: typing.ClassVar[type] = DeleteMutationResponseType


class IsAuthenticatedMutation(MutationPermissionMixin, IsAuthenticated): ...


class IsStaffOrAboveMutation(MutationPermissionMixin, IsStaffOrAbove): ...


class IsHQAdminMutation(MutationPermissionMixin, IsHQAdmin): ...


class IsAuthenticatedDelete(DeleteMutationPermissionMixin, IsAuthenticated): ...


class IsStaffOrAboveDelete(DeleteMutationPermissionMixin, IsStaffOrAbove): ...


class IsHQAdminDelete(DeleteMutationPermissionMixin, IsHQAdmin): ...
