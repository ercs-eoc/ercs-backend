import typing

from django.core.files.uploadedfile import SimpleUploadedFile

from apps.geo.factories import RegionFactory
from apps.pmer.factories import PmerCategoryFactory, PmerDocumentTypeFactory, PmerReportFactory
from apps.pmer.models import PmerCategory, PmerDocumentType, PmerReport
from apps.users.factories import UserFactory
from apps.users.models import User
from main.tests import TestCase


def pdf_upload(name: str = "pmer-report.pdf") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, b"%PDF-1.4 pmer report", content_type="application/pdf")


class TestPmerReportMutations(TestCase):
    class Mutation:
        CREATE_PMER_REPORT = """
            mutation CreatePmerReport($data: PmerReportCreateInput!) {
                createPmerReport(data: $data) {
                    ... on PmerReportTypeMutationResponseType {
                        ok
                        errors
                        result {
                            id
                            title
                            description
                            category { id name }
                            reportType { id name }
                            visibility
                            visibilityDisplay
                            department
                            project
                            region { id name }
                            file { name size url }
                            createdBy { id email }
                        }
                    }
                }
            }
        """

        UPDATE_PMER_REPORT = """
            mutation UpdatePmerReport($id: ID!, $data: PmerReportUpdateInput!) {
                updatePmerReport(id: $id, data: $data) {
                    ... on PmerReportTypeMutationResponseType {
                        ok
                        errors
                        result {
                            id
                            title
                            description
                            category { id name }
                            reportType { id name }
                            visibility
                            department
                            project
                            region { id name }
                        }
                    }
                }
            }
        """

        DELETE_PMER_REPORT = """
            mutation DeletePmerReport($id: ID!) {
                deletePmerReport(id: $id) {
                    ok
                    errors
                }
            }
        """

    @typing.override
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = UserFactory.create()
        cls.other_user = UserFactory.create()
        cls.region = RegionFactory.create(name="Amhara")
        cls.dpr = PmerCategoryFactory.create(name="DPR")
        cls.drr = PmerCategoryFactory.create(name="DRR")
        cls.volunteer = PmerCategoryFactory.create(name="Volunteer Service / Membership")
        cls.strategic_plan = PmerDocumentTypeFactory.create(name="Strategic Plan")
        cls.annual_plan = PmerDocumentTypeFactory.create(name="Annual Plan")
        cls.annual_report = PmerDocumentTypeFactory.create(name="Annual Report")
        cls.mid_term_review = PmerDocumentTypeFactory.create(name="Mid-term Review Report")

    def create_pmer_report(
        self,
        *,
        title: str,
        category: PmerCategory,
        report_type: PmerDocumentType | None = None,
        description: str | None = None,
        department: str | None = None,
        project: str | None = None,
        region: str | None = None,
        visibility: PmerReport.Visibility | None = None,
        file: SimpleUploadedFile | None = None,
        assert_errors: bool = False,
    ) -> dict[str, typing.Any]:
        data: dict[str, typing.Any] = {
            "title": title,
            "category": str(category.pk),
            "reportType": str((report_type or self.annual_report).pk),
            "file": None,
        }
        if description is not None:
            data["description"] = description
        if department is not None:
            data["department"] = department
        if project is not None:
            data["project"] = project
        if region is not None:
            data["region"] = region
        if visibility is not None:
            data["visibility"] = self.genum(visibility)
        return self.query_check(
            self.Mutation.CREATE_PMER_REPORT,
            assert_errors=assert_errors,
            variables={"data": data},
            files={"0": file or pdf_upload()},
            map={"0": ["variables.data.file"]},
        )

    def test_create_pmer_report(self):
        self.force_login(self.user)
        content = self.create_pmer_report(
            title="DRR Baseline Study",
            category=self.drr,
            report_type=self.mid_term_review,
            description="Baseline assessment for DRR programming.",
            department="Disaster Risk Reduction",
            project="Community Resilience",
            region=str(self.region.pk),
            visibility=PmerReport.Visibility.PRIVATE,
        )
        resp = content["data"]["createPmerReport"]
        assert resp["ok"] is True, resp
        assert resp["errors"] is None
        assert resp["result"]["title"] == "DRR Baseline Study"
        assert resp["result"]["description"] == "Baseline assessment for DRR programming."
        assert resp["result"]["category"] == {"id": str(self.drr.pk), "name": "DRR"}
        assert resp["result"]["reportType"] == {"id": str(self.mid_term_review.pk), "name": "Mid-term Review Report"}
        assert resp["result"]["visibility"] == self.genum(PmerReport.Visibility.PRIVATE)
        assert resp["result"]["visibilityDisplay"] == "Private"
        assert resp["result"]["department"] == "Disaster Risk Reduction"
        assert resp["result"]["project"] == "Community Resilience"
        assert resp["result"]["region"] == {"id": str(self.region.pk), "name": "Amhara"}
        assert resp["result"]["file"]["name"].endswith(".pdf")
        assert resp["result"]["createdBy"]["id"] == str(self.user.pk)

    def test_create_pmer_report_without_optional_fields(self):
        self.force_login(self.user)
        content = self.create_pmer_report(title="Minimal Report", category=self.dpr)
        resp = content["data"]["createPmerReport"]
        assert resp["ok"] is True, resp
        assert resp["result"]["description"] is None
        assert resp["result"]["department"] is None
        assert resp["result"]["project"] is None
        assert resp["result"]["region"] is None
        # `visibility` defaults to PUBLIC in the input and on the model
        assert resp["result"]["visibility"] == self.genum(PmerReport.Visibility.PUBLIC)

    def test_create_pmer_report_requires_auth(self):
        self.logout()
        content = self.create_pmer_report(
            title="Unauthorized",
            category=self.dpr,
        )
        self.assert_permission_denied(content, "createPmerReport")
        assert not PmerReport.objects.filter(title="Unauthorized").exists()

    def test_create_pmer_report_rejects_unsupported_file_type(self):
        self.force_login(self.user)
        content = self.create_pmer_report(
            title="Bad File",
            category=self.dpr,
            file=SimpleUploadedFile("payload.exe", b"MZ", content_type="application/octet-stream"),
        )
        resp = content["data"]["createPmerReport"]
        assert resp["ok"] is False, resp
        assert resp["errors"] is not None
        assert not PmerReport.objects.filter(title="Bad File").exists()

    def test_create_pmer_report_rejects_unknown_category(self):
        self.force_login(self.user)
        category = PmerCategoryFactory.create()
        category_id = category.pk
        category.delete()
        content = self.query_check(
            self.Mutation.CREATE_PMER_REPORT,
            variables={
                "data": {
                    "title": "Unknown Category",
                    "category": str(category_id),
                    "reportType": str(self.annual_report.pk),
                    "file": None,
                },
            },
            files={"0": pdf_upload()},
            map={"0": ["variables.data.file"]},
        )
        resp = content["data"]["createPmerReport"]
        assert resp["ok"] is False, resp
        assert not PmerReport.objects.filter(title="Unknown Category").exists()

    def test_create_pmer_report_requires_report_type(self):
        self.force_login(self.user)
        content = self.query_check(
            self.Mutation.CREATE_PMER_REPORT,
            assert_errors=True,
            variables={
                "data": {
                    "title": "No Report Type",
                    "category": str(self.dpr.pk),
                    "file": None,
                },
            },
            files={"0": pdf_upload()},
            map={"0": ["variables.data.file"]},
        )
        assert "errors" in content
        assert not PmerReport.objects.filter(title="No Report Type").exists()

    def test_update_pmer_report(self):
        self.force_login(self.user)
        report = PmerReportFactory.create(
            title="Old Title",
            category=self.dpr,
            department="Old Department",
            project="Old Project",
            region=None,
            visibility=PmerReport.Visibility.PUBLIC,
            created_by=self.user,
        )
        content = self.query_check(
            self.Mutation.UPDATE_PMER_REPORT,
            variables={
                "id": str(report.pk),
                "data": {
                    "title": "New Title",
                    "category": str(self.volunteer.pk),
                    "reportType": str(self.strategic_plan.pk),
                    "department": "Volunteer Service",
                    "project": "Membership Drive",
                    "region": str(self.region.pk),
                    "visibility": self.genum(PmerReport.Visibility.PRIVATE),
                },
            },
        )
        resp = content["data"]["updatePmerReport"]
        assert resp["ok"] is True, resp
        assert resp["result"]["title"] == "New Title"
        assert resp["result"]["category"]["id"] == str(self.volunteer.pk)
        assert resp["result"]["reportType"]["id"] == str(self.strategic_plan.pk)
        assert resp["result"]["visibility"] == self.genum(PmerReport.Visibility.PRIVATE)
        assert resp["result"]["department"] == "Volunteer Service"
        assert resp["result"]["project"] == "Membership Drive"
        assert resp["result"]["region"] == {"id": str(self.region.pk), "name": "Amhara"}

        report.refresh_from_db()
        assert report.title == "New Title"
        assert report.category == self.volunteer
        assert report.report_type == self.strategic_plan
        assert report.visibility == PmerReport.Visibility.PRIVATE
        assert report.department == "Volunteer Service"
        assert report.project == "Membership Drive"
        assert report.region == self.region

    def test_update_pmer_report_is_partial(self):
        """Fields left out of the update input keep their existing values."""
        self.force_login(self.user)
        report = PmerReportFactory.create(
            title="Keep Title",
            category=self.drr,
            report_type=self.annual_plan,
            department="Keep Department",
            project="Keep Project",
            region=self.region,
            visibility=PmerReport.Visibility.PRIVATE,
            created_by=self.user,
        )
        content = self.query_check(
            self.Mutation.UPDATE_PMER_REPORT,
            variables={"id": str(report.pk), "data": {"department": "Changed Department"}},
        )
        resp = content["data"]["updatePmerReport"]
        assert resp["ok"] is True, resp
        assert resp["result"]["title"] == "Keep Title"
        assert resp["result"]["category"]["id"] == str(self.drr.pk)
        assert resp["result"]["reportType"]["id"] == str(self.annual_plan.pk)
        assert resp["result"]["visibility"] == self.genum(PmerReport.Visibility.PRIVATE)
        assert resp["result"]["department"] == "Changed Department"
        assert resp["result"]["project"] == "Keep Project"
        assert resp["result"]["region"] == {"id": str(self.region.pk), "name": "Amhara"}

    def test_update_pmer_report_requires_auth(self):
        self.logout()
        report = PmerReportFactory.create(title="Untouched", created_by=self.user)
        content = self.query_check(
            self.Mutation.UPDATE_PMER_REPORT,
            variables={"id": str(report.pk), "data": {"title": "Hacked"}},
        )
        self.assert_permission_denied(content, "updatePmerReport")
        report.refresh_from_db()
        assert report.title == "Untouched"

    def test_delete_pmer_report(self):
        self.force_login(self.user)
        report = PmerReportFactory.create(created_by=self.user)
        content = self.query_check(
            self.Mutation.DELETE_PMER_REPORT,
            variables={"id": str(report.pk)},
        )
        resp = content["data"]["deletePmerReport"]
        assert resp["ok"] is True, resp
        assert not PmerReport.objects.filter(pk=report.pk).exists()

    def test_delete_pmer_report_requires_auth(self):
        self.logout()
        report = PmerReportFactory.create(created_by=self.user)
        content = self.query_check(
            self.Mutation.DELETE_PMER_REPORT,
            variables={"id": str(report.pk)},
        )
        self.assert_permission_denied(content, "deletePmerReport")
        assert PmerReport.objects.filter(pk=report.pk).exists()

    def test_deleting_missing_pmer_report_is_reported_on_the_payload(self):
        self.force_login(self.user)
        report = PmerReportFactory.create(created_by=self.user)
        report_id = str(report.pk)
        report.delete()
        content = self.query_check(
            self.Mutation.DELETE_PMER_REPORT,
            variables={"id": report_id},
        )
        resp = content["data"]["deletePmerReport"]
        assert resp["ok"] is False, resp
        assert resp["errors"][0]["messages"] == "This PMER Report no longer exists. It may already have been deleted."


class TestPmerLookupMutations(TestCase):
    """CRUD for the user-managed PMER categories and document types."""

    LOOKUPS: typing.ClassVar = [
        # (graphql suffix, input type, model, factory)
        ("PmerCategory", "PmerCategoryInput", PmerCategory, PmerCategoryFactory),
        ("PmerDocumentType", "PmerDocumentTypeInput", PmerDocumentType, PmerDocumentTypeFactory),
    ]

    @typing.override
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.viewer = UserFactory.create()
        cls.staff = UserFactory.create(role=User.Role.STAFF)

    @staticmethod
    def create_mutation(name: str, input_type: str) -> str:
        return f"""
            mutation Create($data: {input_type}!) {{
                create{name}(data: $data) {{
                    ... on {name}TypeMutationResponseType {{ ok errors result {{ id name }} }}
                }}
            }}
        """

    @staticmethod
    def update_mutation(name: str, input_type: str) -> str:
        return f"""
            mutation Update($id: ID!, $data: {input_type}!) {{
                update{name}(id: $id, data: $data) {{
                    ... on {name}TypeMutationResponseType {{ ok errors result {{ id name }} }}
                }}
            }}
        """

    @staticmethod
    def delete_mutation(name: str) -> str:
        return f"""
            mutation Delete($id: ID!) {{
                delete{name}(id: $id) {{ ok errors }}
            }}
        """

    def test_staff_can_create_update_delete(self):
        self.force_login(self.staff)
        for name, input_type, model, _ in self.LOOKUPS:
            op = name[0].lower() + name[1:]
            content = self.query_check(self.create_mutation(name, input_type), variables={"data": {"name": "Original"}})
            resp = content["data"][f"create{name}"]
            assert resp["ok"] is True, resp
            obj_id = resp["result"]["id"]
            assert resp["result"]["name"] == "Original"

            content = self.query_check(
                self.update_mutation(name, input_type),
                variables={"id": obj_id, "data": {"name": "Renamed"}},
            )
            resp = content["data"][f"update{name}"]
            assert resp["ok"] is True, resp
            assert model.objects.get(pk=obj_id).name == "Renamed"

            content = self.query_check(self.delete_mutation(name), variables={"id": obj_id})
            assert content["data"][f"delete{name}"]["ok"] is True, (op, content)
            assert not model.objects.filter(pk=obj_id).exists()

    def test_name_must_be_unique(self):
        self.force_login(self.staff)
        for name, input_type, model, factory in self.LOOKUPS:
            factory.create(name="Duplicate")
            content = self.query_check(self.create_mutation(name, input_type), variables={"data": {"name": "Duplicate"}})
            resp = content["data"][f"create{name}"]
            assert resp["ok"] is False, resp
            assert model.objects.filter(name="Duplicate").count() == 1

    def test_viewer_cannot_create(self):
        self.force_login(self.viewer)
        for name, input_type, model, _ in self.LOOKUPS:
            content = self.query_check(self.create_mutation(name, input_type), variables={"data": {"name": "Blocked"}})
            self.assert_permission_denied(content, f"create{name}")
            assert not model.objects.filter(name="Blocked").exists()

    def test_viewer_cannot_delete(self):
        self.force_login(self.viewer)
        for name, _, model, factory in self.LOOKUPS:
            obj = factory.create()
            content = self.query_check(self.delete_mutation(name), variables={"id": str(obj.pk)})
            self.assert_permission_denied(content, f"delete{name}")
            assert model.objects.filter(pk=obj.pk).exists()

    def test_cannot_delete_when_in_use(self):
        self.force_login(self.staff)
        report = PmerReportFactory.create()
        for name, obj in (("PmerCategory", report.category), ("PmerDocumentType", report.report_type)):
            content = self.query_check(self.delete_mutation(name), variables={"id": str(obj.pk)})
            resp = content["data"][f"delete{name}"]
            assert resp["ok"] is False, resp
            assert "still linked to 1 PMER Report" in resp["errors"][0]["messages"]
            assert type(obj).objects.filter(pk=obj.pk).exists()
