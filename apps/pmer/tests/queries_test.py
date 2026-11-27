import typing

from apps.geo.factories import RegionFactory
from apps.pmer.factories import PmerCategoryFactory, PmerDocumentTypeFactory, PmerReportFactory
from apps.pmer.models import PmerReport
from apps.users.factories import UserFactory
from main.tests import TestCase


class TestPmerReportQueries(TestCase):
    class Query:
        PMER_REPORTS = """
            query PmerReports($pagination: OffsetPaginationInput, $filters: PmerReportFilter) {
                pmerReports(pagination: $pagination, filters: $filters, ordering: {title: ASC}) {
                    totalCount
                    pageInfo { offset limit }
                    results {
                        id
                        title
                        description
                        category { id name }
                        reportType { id name }
                        visibility
                        visibilityDisplay
                        department
                        project
                        region { id name level }
                        file { name size url contentType }
                        createdBy { id email fullName }
                        createdAt
                    }
                }
            }
        """

        PMER_REPORT = """
            query PmerReport($id: ID!) {
                pmerReport(id: $id) {
                    id
                    title
                    category { id name }
                    reportType { id name }
                    visibility
                    department
                    project
                    region { id name }
                }
            }
        """

    @typing.override
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = UserFactory.create()
        cls.afar = RegionFactory.create(name="Afar")
        cls.dpr = PmerCategoryFactory.create(name="DPR")
        cls.health_and_wash = PmerCategoryFactory.create(name="Health & WASH")
        cls.strategic_plan = PmerDocumentTypeFactory.create(name="Strategic Plan")
        cls.annual_report = PmerDocumentTypeFactory.create(name="Annual Report")
        cls.tigray = RegionFactory.create(name="Tigray")
        cls.dpr_report = PmerReportFactory.create(
            title="Annual Preparedness Review",
            category=cls.dpr,
            report_type=cls.strategic_plan,
            department="Disaster Management",
            project="National Preparedness Programme",
            region=cls.afar,
            visibility=PmerReport.Visibility.PUBLIC,
            created_by=cls.user,
        )
        cls.wash_report = PmerReportFactory.create(
            title="WASH Monitoring Q1",
            category=cls.health_and_wash,
            report_type=cls.annual_report,
            department="Health",
            project="WASH Scale-Up",
            region=cls.tigray,
            visibility=PmerReport.Visibility.PRIVATE,
            created_by=cls.user,
            file__filename="wash-monitoring.xlsx",
        )

    def test_pmer_reports_authenticated(self):
        self.force_login(self.user)
        content = self.query_check(
            self.Query.PMER_REPORTS,
            variables={"pagination": {"limit": 10, "offset": 0}},
        )
        resp = content["data"]["pmerReports"]
        assert resp["totalCount"] == 2
        # ordered by title ASC
        assert [result["title"] for result in resp["results"]] == [
            "Annual Preparedness Review",
            "WASH Monitoring Q1",
        ]

    def test_pmer_report_detail(self):
        self.force_login(self.user)
        content = self.query_check(
            self.Query.PMER_REPORT,
            variables={"id": str(self.dpr_report.pk)},
        )
        resp = content["data"]["pmerReport"]
        assert resp["id"] == str(self.dpr_report.pk)
        assert resp["category"] == {"id": str(self.dpr.pk), "name": "DPR"}
        assert resp["reportType"] == {"id": str(self.strategic_plan.pk), "name": "Strategic Plan"}
        assert resp["visibility"] == self.genum(PmerReport.Visibility.PUBLIC)
        assert resp["department"] == "Disaster Management"
        assert resp["project"] == "National Preparedness Programme"
        assert resp["region"] == {"id": str(self.afar.pk), "name": "Afar"}

    def test_filter_by_category(self):
        self.force_login(self.user)
        content = self.query_check(
            self.Query.PMER_REPORTS,
            variables={
                "pagination": {"limit": 10, "offset": 0},
                "filters": {"categoryId": str(self.health_and_wash.pk)},
            },
        )
        resp = content["data"]["pmerReports"]
        assert resp["totalCount"] == 1
        result = resp["results"][0]
        assert result["category"] == {"id": str(self.health_and_wash.pk), "name": "Health & WASH"}
        assert result["file"]["name"]

    def test_filter_by_title(self):
        self.force_login(self.user)
        content = self.query_check(
            self.Query.PMER_REPORTS,
            variables={
                "pagination": {"limit": 10, "offset": 0},
                "filters": {"title": {"iContains": "wash monitoring"}},
            },
        )
        resp = content["data"]["pmerReports"]
        assert resp["totalCount"] == 1
        assert resp["results"][0]["id"] == str(self.wash_report.pk)

    def test_filter_by_department(self):
        self.force_login(self.user)
        content = self.query_check(
            self.Query.PMER_REPORTS,
            variables={
                "pagination": {"limit": 10, "offset": 0},
                "filters": {"department": {"iExact": "health"}},
            },
        )
        resp = content["data"]["pmerReports"]
        assert resp["totalCount"] == 1
        assert resp["results"][0]["department"] == "Health"

    def test_filter_by_project(self):
        self.force_login(self.user)
        content = self.query_check(
            self.Query.PMER_REPORTS,
            variables={
                "pagination": {"limit": 10, "offset": 0},
                "filters": {"project": {"iContains": "preparedness"}},
            },
        )
        resp = content["data"]["pmerReports"]
        assert resp["totalCount"] == 1
        assert resp["results"][0]["project"] == "National Preparedness Programme"

    def test_file_content_type(self):
        self.force_login(self.user)
        content = self.query_check(
            self.Query.PMER_REPORTS,
            variables={"pagination": {"limit": 10, "offset": 0}},
        )
        assert [result["file"]["contentType"] for result in content["data"]["pmerReports"]["results"]] == [
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ]

    def file_types_check(self, file_types: list[str]) -> list[str]:
        self.force_login(self.user)
        content = self.query_check(
            self.Query.PMER_REPORTS,
            variables={
                "pagination": {"limit": 10, "offset": 0},
                "filters": {"fileTypes": file_types},
            },
        )
        return [result["id"] for result in content["data"]["pmerReports"]["results"]]

    def test_filter_by_file_types(self):
        assert self.file_types_check(["PDF"]) == [str(self.dpr_report.pk)]
        assert self.file_types_check(["EXCEL"]) == [str(self.wash_report.pk)]
        assert self.file_types_check(["PDF", "EXCEL"]) == [str(self.dpr_report.pk), str(self.wash_report.pk)]
        assert self.file_types_check(["IMAGE"]) == []

    def search_check(self, value: str) -> list[dict]:
        self.force_login(self.user)
        content = self.query_check(
            self.Query.PMER_REPORTS,
            variables={
                "pagination": {"limit": 10, "offset": 0},
                "filters": {"search": value},
            },
        )
        return content["data"]["pmerReports"]["results"]

    def test_search_matches_title(self):
        results = self.search_check("monitoring")
        assert [result["id"] for result in results] == [str(self.wash_report.pk)]

    def test_search_matches_department(self):
        results = self.search_check("disaster management")
        assert [result["id"] for result in results] == [str(self.dpr_report.pk)]

    def test_search_matches_project(self):
        results = self.search_check("scale-up")
        assert [result["id"] for result in results] == [str(self.wash_report.pk)]

    def test_search_matches_across_fields(self):
        """`wash_report` matches on both title and project -- it must be returned once."""
        results = self.search_check("wash")
        assert [result["id"] for result in results] == [str(self.wash_report.pk)]

    def test_search_is_case_insensitive(self):
        results = self.search_check("PREPAREDNESS")
        assert [result["id"] for result in results] == [str(self.dpr_report.pk)]

    def test_search_no_match(self):
        assert self.search_check("nonexistent") == []

    def test_filter_by_region(self):
        self.force_login(self.user)
        content = self.query_check(
            self.Query.PMER_REPORTS,
            variables={
                "pagination": {"limit": 10, "offset": 0},
                "filters": {"regionId": str(self.tigray.pk)},
            },
        )
        resp = content["data"]["pmerReports"]
        assert resp["totalCount"] == 1
        result = resp["results"][0]
        assert result["id"] == str(self.wash_report.pk)
        assert result["region"] == {
            "id": str(self.tigray.pk),
            "name": "Tigray",
            "level": self.genum(self.tigray.Level.REGION),
        }

    def test_filter_by_report_type(self):
        self.force_login(self.user)
        content = self.query_check(
            self.Query.PMER_REPORTS,
            variables={
                "pagination": {"limit": 10, "offset": 0},
                "filters": {"reportTypeId": str(self.strategic_plan.pk)},
            },
        )
        resp = content["data"]["pmerReports"]
        assert resp["totalCount"] == 1
        result = resp["results"][0]
        assert result["id"] == str(self.dpr_report.pk)
        assert result["reportType"] == {"id": str(self.strategic_plan.pk), "name": "Strategic Plan"}

    def test_filter_by_visibility(self):
        self.force_login(self.user)
        content = self.query_check(
            self.Query.PMER_REPORTS,
            variables={
                "pagination": {"limit": 10, "offset": 0},
                "filters": {"visibility": self.genum(PmerReport.Visibility.PRIVATE)},
            },
        )
        resp = content["data"]["pmerReports"]
        assert resp["totalCount"] == 1
        result = resp["results"][0]
        assert result["id"] == str(self.wash_report.pk)
        assert result["visibility"] == self.genum(PmerReport.Visibility.PRIVATE)
        assert result["visibilityDisplay"] == "Private"

    def test_authenticated_user_sees_private_reports(self):
        """`PmerReportType.get_queryset` only hides PRIVATE rows from anonymous callers."""
        self.force_login(self.user)
        content = self.query_check(
            self.Query.PMER_REPORTS,
            variables={"pagination": {"limit": 10, "offset": 0}},
        )
        resp = content["data"]["pmerReports"]
        assert resp["totalCount"] == 2
        assert {result["visibility"] for result in resp["results"]} == {
            self.genum(PmerReport.Visibility.PUBLIC),
            self.genum(PmerReport.Visibility.PRIVATE),
        }

    def test_region_is_nullable(self):
        self.force_login(self.user)
        no_region = PmerReportFactory.create(title="No Region", region=None, created_by=self.user)
        content = self.query_check(
            self.Query.PMER_REPORT,
            variables={"id": str(no_region.pk)},
        )
        assert content["data"]["pmerReport"]["region"] is None


class TestPmerLookupQueries(TestCase):
    class Query:
        PMER_CATEGORIES = """
            query PmerCategories($filters: PmerCategoryFilter) {
                pmerCategories(filters: $filters) {
                    totalCount
                    results { id name }
                }
            }
        """

        PMER_DOCUMENT_TYPES = """
            query PmerDocumentTypes($filters: PmerDocumentTypeFilter) {
                pmerDocumentTypes(filters: $filters) {
                    totalCount
                    results { id name }
                }
            }
        """

    @typing.override
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.drr = PmerCategoryFactory.create(name="DRR")
        cls.dpr = PmerCategoryFactory.create(name="DPR")
        cls.annual_plan = PmerDocumentTypeFactory.create(name="Annual Plan")
        cls.annual_report = PmerDocumentTypeFactory.create(name="Annual Report")
        cls.strategic_plan = PmerDocumentTypeFactory.create(name="Strategic Plan")

    def test_pmer_categories(self):
        content = self.query_check(self.Query.PMER_CATEGORIES)
        resp = content["data"]["pmerCategories"]
        assert resp["totalCount"] == 2
        assert {(r["id"], r["name"]) for r in resp["results"]} == {
            (str(self.dpr.pk), "DPR"),
            (str(self.drr.pk), "DRR"),
        }

    def test_pmer_categories_search(self):
        content = self.query_check(self.Query.PMER_CATEGORIES, variables={"filters": {"search": "dr"}})
        assert [r["id"] for r in content["data"]["pmerCategories"]["results"]] == [str(self.drr.pk)]

    def test_pmer_document_types_search(self):
        content = self.query_check(self.Query.PMER_DOCUMENT_TYPES, variables={"filters": {"search": "annual"}})
        resp = content["data"]["pmerDocumentTypes"]
        assert resp["totalCount"] == 2
        assert {r["name"] for r in resp["results"]} == {"Annual Plan", "Annual Report"}
