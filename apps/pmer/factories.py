from factory.declarations import Sequence, SubFactory
from factory.django import DjangoModelFactory, FileField

from apps.users.factories import UserFactory

from .models import PmerCategory, PmerDocumentType, PmerReport


class PmerCategoryFactory(DjangoModelFactory[PmerCategory]):
    name = Sequence(lambda n: f"PMER Category {n}")

    class Meta:  # type: ignore[misc]
        model = PmerCategory


class PmerDocumentTypeFactory(DjangoModelFactory[PmerDocumentType]):
    name = Sequence(lambda n: f"PMER Document Type {n}")

    class Meta:  # type: ignore[misc]
        model = PmerDocumentType


class PmerReportFactory(DjangoModelFactory[PmerReport]):
    title = Sequence(lambda n: f"PMER Report {n}")
    description = Sequence(lambda n: f"PMER report description {n}")
    file = FileField(filename="pmer-report.pdf")
    category = SubFactory(PmerCategoryFactory)
    report_type = SubFactory(PmerDocumentTypeFactory)
    visibility = PmerReport.Visibility.PUBLIC
    created_by = SubFactory(UserFactory)

    class Meta:  # type: ignore[misc]
        model = PmerReport
