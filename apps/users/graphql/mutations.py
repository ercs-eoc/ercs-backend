import strawberry
import strawberry_django
from asgiref.sync import sync_to_async
from strawberry_django.auth.mutations import resolve_login, resolve_logout
from strawberry_django.resolvers import django_resolver

from apps.users.models import User
from apps.users.serializers import UserSerializer
from main.graphql.context import Info
from main.graphql.permissions import IsAuthenticatedMutation, IsHQAdminDelete, IsHQAdminMutation
from utils.graphql.drf import MutationCustomErrorType
from utils.graphql.mutations import ModelMutation
from utils.graphql.types import DeleteMutationResponseType, MutationResponseType

from .inputs import PasswordUpdateInput, UserCreateInput, UserUpdateInput
from .types import UserMeType, UserType


# NOTE:
# resolve_login accepts a username kwarg, but Django's authentication backend resolves
# credentials via USERNAME_FIELD which is set to "email" on our User model so passing the email as username works correctly.
# django_resolver ensures synchronous ORM calls (authenticate, login, session writes)
# are safe in both WSGI and ASGI execution contexts.
@strawberry.type
class Mutation:
    @strawberry.mutation
    @django_resolver
    def login(self, info: Info, email: str, password: str) -> UserMeType:
        return resolve_login(info, username=email, password=password)  # type: ignore[reportReturnType]

    @strawberry.mutation
    @django_resolver
    def logout(self, info: Info) -> bool:
        return resolve_logout(info)  # type: ignore[reportReturnType]

    @strawberry_django.mutation(permission_classes=[IsHQAdminMutation])
    async def create_user(
        self,
        info: Info,
        data: UserCreateInput,
    ) -> MutationResponseType[UserType]:
        return await ModelMutation(UserSerializer).handle_create_mutation(data, info)

    @strawberry_django.mutation(permission_classes=[IsHQAdminMutation])
    async def update_user(
        self,
        info: Info,
        id: strawberry.ID,
        data: UserUpdateInput,
    ) -> MutationResponseType[UserType]:
        instance = await User.objects.aget(id=id)
        return await ModelMutation(UserSerializer).handle_update_mutation(data, info, instance)

    @strawberry_django.mutation(permission_classes=[IsHQAdminDelete], handle_django_errors=False)
    async def delete_user(
        self,
        info: Info,
        id: strawberry.ID,
    ) -> DeleteMutationResponseType:
        user = await User.objects.filter(id=id).afirst()
        if user is None:
            return DeleteMutationResponseType(
                ok=False,
                errors=MutationCustomErrorType.generate_message(
                    "This User no longer exists. It may already have been deleted.",
                ),
            )
        current_user: User = info.context.request.user  # type: ignore[reportAssignmentType]
        if user.role == User.Role.HQ_ADMIN and user.pk == current_user.pk:
            return DeleteMutationResponseType(
                ok=False,
                errors=MutationCustomErrorType.generate_message(
                    "You cannot deactivate your own HQ admin account.",
                ),
            )
        user.is_active = False
        await user.asave(update_fields=["is_active"])
        return DeleteMutationResponseType(ok=True)

    @strawberry_django.mutation(permission_classes=[IsHQAdminMutation])
    async def reset_user_password(
        self,
        info: Info,
        id: strawberry.ID,
        new_password: str,
    ) -> MutationResponseType[UserType]:
        instance = await User.objects.aget(id=id)
        await sync_to_async(instance.set_password)(new_password)
        await instance.asave()
        return MutationResponseType(result=instance)  # type: ignore[reportReturnType]

    @strawberry_django.mutation(permission_classes=[IsAuthenticatedMutation])
    async def update_my_password(
        self,
        info: Info,
        data: PasswordUpdateInput,
    ) -> MutationResponseType[UserType]:
        user: User = info.context.request.user  # type: ignore[reportAssignmentType]
        password_valid = await sync_to_async(user.check_password)(data.current_password)
        if not password_valid:
            return MutationResponseType(
                ok=False,
                errors=MutationCustomErrorType.generate_message("Current password is incorrect."),
            )
        await sync_to_async(user.set_password)(data.new_password)
        await user.asave()
        return MutationResponseType(result=user)  # type: ignore[reportReturnType]
