import dataclasses

import strawberry

from apps.dashboards.models import DashboardPage
from apps.geo.models import AdminAreaLevel
from apps.kobo.models import KoboForm
from apps.reports.models import DocumentExtractionStatus, LinkType, ReportContentType, ReportType, ReportVisibility
from apps.teams.models import TeamMemberSex
from apps.users.models import UserRole

ENUM_TO_STRAWBERRY_ENUMS: list[type] = [
    AdminAreaLevel,
    UserRole,
    DocumentExtractionStatus,
    LinkType,
    ReportContentType,
    ReportType,
    ReportVisibility,
    DashboardPage,
    TeamMemberSex,
    KoboForm,
]


class AppEnumData:
    def __init__(self, enum):  # type: ignore[reportMissingParameterType]
        self.enum = enum

    @property
    def key(self):
        return self.enum

    @property
    def label(self):
        return str(self.enum.label)


def generate_app_enum_collection_data(name: str):
    return type(
        name,
        (),
        {enum.__name__: [AppEnumData(e) for e in enum] for enum in ENUM_TO_STRAWBERRY_ENUMS},  # type: ignore[reportGeneralTypeIssues]
    )


AppEnumCollectionData = generate_app_enum_collection_data(
    "AppEnumCollectionData",
)


def generate_type_for_enum(name: str, Enum):  # type: ignore[reportMissingParameterType]
    return strawberry.type(
        dataclasses.make_dataclass(
            f"AppEnumCollection{name}",
            [
                ("key", Enum),
                ("label", str),
            ],
        ),
    )


def _enum_type(name: str, Enum):  # type: ignore[reportMissingParameterType]
    EnumType = generate_type_for_enum(name, Enum)

    @strawberry.field
    def _field() -> list[EnumType]:  # type: ignore[reportGeneralTypeIssues]
        return [
            EnumType(
                key=e,
                label=e.label,
            )
            for e in Enum
        ]

    return list[EnumType], _field


def generate_type_for_enums():
    enum_fields = [
        (
            enum.__name__,
            *_enum_type(enum.__name__, enum),
        )
        for enum in ENUM_TO_STRAWBERRY_ENUMS
    ]
    return strawberry.type(
        dataclasses.make_dataclass(
            "AppEnumCollection",
            enum_fields,
        ),
    )


AppEnumCollection = generate_type_for_enums()
