import strawberry
from strawberry.file_uploads import Upload

from apps.reports.models import LinkType, ReportContentType, ReportType, ReportVisibility


@strawberry.input
class LinkCreateInput:
    title: str
    url: str
    link_type: LinkType
    description: str | None = strawberry.UNSET


@strawberry.input
class LinkUpdateInput:
    title: str | None = strawberry.UNSET
    url: str | None = strawberry.UNSET
    link_type: LinkType | None = strawberry.UNSET
    description: str | None = strawberry.UNSET


@strawberry.input
class ReportCreateInput:
    title: str
    content_type: ReportContentType
    description: str | None = strawberry.UNSET
    cover_image: Upload | None = strawberry.UNSET
    file: Upload | None = strawberry.UNSET
    iframe_url: str | None = strawberry.UNSET
    visibility: ReportVisibility = ReportVisibility.PUBLIC
    report_type: ReportType = ReportType.REPORT
    thematic_area: strawberry.ID
    region: strawberry.ID | None = strawberry.UNSET
    disaster_type: str | None = strawberry.UNSET
    owner: str | None = strawberry.UNSET
    published_at: str


@strawberry.input
class ReportUpdateInput:
    title: str | None = strawberry.UNSET
    description: str | None = strawberry.UNSET
    cover_image: Upload | None = strawberry.UNSET
    file: Upload | None = strawberry.UNSET
    visibility: ReportVisibility | None = strawberry.UNSET
    report_type: ReportType | None = strawberry.UNSET
    thematic_area: strawberry.ID | None = strawberry.UNSET
    region: strawberry.ID | None = strawberry.UNSET
    disaster_type: str | None = strawberry.UNSET
    owner: str | None = strawberry.UNSET
    published_at: str | None = strawberry.UNSET
