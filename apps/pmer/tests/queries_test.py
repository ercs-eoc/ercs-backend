import typing

from apps.geo.factories import RegionFactory
from apps.pmer.factories import PmerReportFactory
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
                        category
                        categoryDisplay
                        reportType
                        reportTypeDisplay
                        visibility
                        visibilityDisplay
                        department
                        project
                        region { id name level }
                        file { name size url }
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
                    category
                    reportType
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
        cls.tigray = RegionFactory.create(name="Tigray")
        cls.dpr_report = PmerReportFactory.create(
            title="Annual Preparedness Review",
            category=PmerReport.Category.DPR,
            report_type=PmerReport.DocumentType.STRATEGIC_PLAN,
            department="Disaster Management",
            project="National Preparedness Programme",
            region=cls.afar,
            visibility=PmerReport.Visibility.PUBLIC,
            created_by=cls.user,
        )
        cls.wash_report = PmerReportFactory.create(
            title="WASH Monitoring Q1",
            category=PmerReport.Category.HEALTH_AND_WASH,
            report_type=PmerReport.DocumentType.ANNUAL_REPORT,
            department="Health",
            project="WASH Scale-Up",
            region=cls.tigray,
            visibility=PmerReport.Visibility.PRIVATE,
            created_by=cls.user,
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
        assert resp["category"] == self.genum(PmerReport.Category.DPR)
        assert resp["reportType"] == self.genum(PmerReport.DocumentType.STRATEGIC_PLAN)
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
                "filters": {"category": self.genum(PmerReport.Category.HEALTH_AND_WASH)},
            },
        )
        resp = content["data"]["pmerReports"]
        assert resp["totalCount"] == 1
        result = resp["results"][0]
        assert result["category"] == self.genum(PmerReport.Category.HEALTH_AND_WASH)
        assert result["categoryDisplay"] == "Health & WASH"
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
                "filters": {"reportType": self.genum(PmerReport.DocumentType.STRATEGIC_PLAN)},
            },
        )
        resp = content["data"]["pmerReports"]
        assert resp["totalCount"] == 1
        result = resp["results"][0]
        assert result["id"] == str(self.dpr_report.pk)
        assert result["reportType"] == self.genum(PmerReport.DocumentType.STRATEGIC_PLAN)
        assert result["reportTypeDisplay"] == "Strategic Plan"

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
