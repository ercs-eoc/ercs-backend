import strawberry
import strawberry_django

from apps.pmer.models import PmerCategory, PmerDocumentType, PmerReport
from apps.pmer.serializers import PmerCategorySerializer, PmerDocumentTypeSerializer, PmerReportSerializer
from main.graphql.context import Info
from main.graphql.permissions import (
    IsAuthenticatedDelete,
    IsAuthenticatedMutation,
    IsStaffOrAboveDelete,
    IsStaffOrAboveMutation,
)
from utils.graphql.mutations import ModelMutation, handle_delete_mutation
from utils.graphql.types import DeleteMutationResponseType, MutationResponseType

from .inputs import PmerCategoryInput, PmerDocumentTypeInput, PmerReportCreateInput, PmerReportUpdateInput
from .types import PmerCategoryType, PmerDocumentTypeType, PmerReportType


@strawberry.type
class Mutation:
    @strawberry_django.mutation(permission_classes=[IsStaffOrAboveMutation])
    async def create_pmer_category(
        self,
        info: Info,
        data: PmerCategoryInput,
    ) -> MutationResponseType[PmerCategoryType]:
        return await ModelMutation(PmerCategorySerializer).handle_create_mutation(data, info)

    @strawberry_django.mutation(permission_classes=[IsStaffOrAboveMutation])
    async def update_pmer_category(
        self,
        info: Info,
        id: strawberry.ID,
        data: PmerCategoryInput,
    ) -> MutationResponseType[PmerCategoryType]:
        instance = await PmerCategory.objects.aget(id=id)
        return await ModelMutation(PmerCategorySerializer).handle_update_mutation(data, info, instance)

    @strawberry_django.mutation(permission_classes=[IsStaffOrAboveDelete], handle_django_errors=False)
    async def delete_pmer_category(
        self,
        info: Info,
        id: strawberry.ID,
    ) -> DeleteMutationResponseType:
        return await handle_delete_mutation(PmerCategory, id=id)

    @strawberry_django.mutation(permission_classes=[IsStaffOrAboveMutation])
    async def create_pmer_document_type(
        self,
        info: Info,
        data: PmerDocumentTypeInput,
    ) -> MutationResponseType[PmerDocumentTypeType]:
        return await ModelMutation(PmerDocumentTypeSerializer).handle_create_mutation(data, info)

    @strawberry_django.mutation(permission_classes=[IsStaffOrAboveMutation])
    async def update_pmer_document_type(
        self,
        info: Info,
        id: strawberry.ID,
        data: PmerDocumentTypeInput,
    ) -> MutationResponseType[PmerDocumentTypeType]:
        instance = await PmerDocumentType.objects.aget(id=id)
        return await ModelMutation(PmerDocumentTypeSerializer).handle_update_mutation(data, info, instance)

    @strawberry_django.mutation(permission_classes=[IsStaffOrAboveDelete], handle_django_errors=False)
    async def delete_pmer_document_type(
        self,
        info: Info,
        id: strawberry.ID,
    ) -> DeleteMutationResponseType:
        return await handle_delete_mutation(PmerDocumentType, id=id)

    @strawberry_django.mutation(permission_classes=[IsAuthenticatedMutation])
    async def create_pmer_report(
        self,
        info: Info,
        data: PmerReportCreateInput,
    ) -> MutationResponseType[PmerReportType]:
        return await ModelMutation(PmerReportSerializer).handle_create_mutation(data, info)

    @strawberry_django.mutation(permission_classes=[IsAuthenticatedMutation])
    async def update_pmer_report(
        self,
        info: Info,
        id: strawberry.ID,
        data: PmerReportUpdateInput,
    ) -> MutationResponseType[PmerReportType]:
        instance = await PmerReport.objects.aget(id=id)
        return await ModelMutation(PmerReportSerializer).handle_update_mutation(data, info, instance)

    @strawberry_django.mutation(permission_classes=[IsAuthenticatedDelete], handle_django_errors=False)
    async def delete_pmer_report(
        self,
        info: Info,
        id: strawberry.ID,
    ) -> DeleteMutationResponseType:
        return await handle_delete_mutation(PmerReport, id=id)
