import strawberry
import strawberry_django

from apps.reports.extraction import trigger_document_extraction
from apps.reports.models import DocumentExtractionRun, Link, Report, ThematicArea
from apps.reports.models import ReportType as ReportTypeEnum
from apps.reports.serializers import LinkSerializer, ReportSerializer, ThematicAreaSerializer
from main.graphql.context import Info
from main.graphql.permissions import (
    IsAuthenticatedDelete,
    IsAuthenticatedMutation,
    IsStaffOrAboveDelete,
    IsStaffOrAboveMutation,
)
from utils.graphql.mutations import ModelMutation, handle_delete_mutation
from utils.graphql.types import DeleteMutationResponseType, MutationResponseType

from .inputs import LinkCreateInput, LinkUpdateInput, ReportCreateInput, ReportUpdateInput
from .types import LinkType, ReportType, ThematicAreaType


@strawberry.input
class ThematicAreaInput:
    name: str


@strawberry.type
class Mutation:
    @strawberry_django.mutation(permission_classes=[IsStaffOrAboveMutation])
    async def create_thematic_area(
        self,
        info: Info,
        data: ThematicAreaInput,
    ) -> MutationResponseType[ThematicAreaType]:
        return await ModelMutation(ThematicAreaSerializer).handle_create_mutation(data, info)

    @strawberry_django.mutation(permission_classes=[IsStaffOrAboveMutation])
    async def update_thematic_area(
        self,
        info: Info,
        id: strawberry.ID,
        data: ThematicAreaInput,
    ) -> MutationResponseType[ThematicAreaType]:
        instance = await ThematicArea.objects.aget(id=id)
        return await ModelMutation(ThematicAreaSerializer).handle_update_mutation(data, info, instance)

    @strawberry_django.mutation(permission_classes=[IsStaffOrAboveDelete], handle_django_errors=False)
    async def delete_thematic_area(
        self,
        info: Info,
        id: strawberry.ID,
    ) -> DeleteMutationResponseType:
        return await handle_delete_mutation(ThematicArea, id=id)

    @strawberry_django.mutation(permission_classes=[IsAuthenticatedMutation])
    async def create_report(
        self,
        info: Info,
        data: ReportCreateInput,
    ) -> MutationResponseType[ReportType]:
        response = await ModelMutation(ReportSerializer).handle_create_mutation(data, info)
        if response.ok and response.result and response.result.report_type == ReportTypeEnum.REPORT:
            await trigger_document_extraction(
                response.result,
                trigger=DocumentExtractionRun.Trigger.REPORT_CREATED,
            )
        return response

    @strawberry_django.mutation(permission_classes=[IsAuthenticatedMutation])
    async def update_report(
        self,
        info: Info,
        id: strawberry.ID,
        data: ReportUpdateInput,
    ) -> MutationResponseType[ReportType]:
        instance = await Report.objects.aget(id=id)
        response = await ModelMutation(ReportSerializer).handle_update_mutation(data, info, instance)
        file_replaced = data.file is not strawberry.UNSET and data.file is not None
        if response.ok and response.result and file_replaced and response.result.report_type == ReportTypeEnum.REPORT:
            await trigger_document_extraction(
                response.result,
                trigger=DocumentExtractionRun.Trigger.FILE_REPLACED,
            )
        return response

    @strawberry_django.mutation(permission_classes=[IsStaffOrAboveMutation])
    async def create_link(
        self,
        info: Info,
        data: LinkCreateInput,
    ) -> MutationResponseType[LinkType]:
        return await ModelMutation(LinkSerializer).handle_create_mutation(data, info)

    @strawberry_django.mutation(permission_classes=[IsStaffOrAboveMutation])
    async def update_link(
        self,
        info: Info,
        id: strawberry.ID,
        data: LinkUpdateInput,
    ) -> MutationResponseType[LinkType]:
        instance = await Link.objects.aget(id=id)
        return await ModelMutation(LinkSerializer).handle_update_mutation(data, info, instance)

    @strawberry_django.mutation(permission_classes=[IsStaffOrAboveDelete], handle_django_errors=False)
    async def delete_link(
        self,
        info: Info,
        id: strawberry.ID,
    ) -> DeleteMutationResponseType:
        return await handle_delete_mutation(Link, id=id)

    @strawberry_django.mutation(permission_classes=[IsAuthenticatedDelete], handle_django_errors=False)
    async def delete_report(
        self,
        info: Info,
        id: strawberry.ID,
    ) -> DeleteMutationResponseType:
        return await handle_delete_mutation(Report, id=id)
