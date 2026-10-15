import typing
from unittest.mock import patch

from apps.reports.factories import LinkFactory, ReportFactory, ThematicAreaFactory
from apps.reports.models import DocumentExtractionRun, Link, Report, ThematicArea
from apps.users.factories import UserFactory
from apps.users.models import User
from main.tests import TestCase


class TestReportMutations(TestCase):
    PUBLISHED_AT = "2026-01-15T00:00:00+00:00"

    class Mutation:
        DELETE_REPORT = """
            mutation DeleteReport($id: ID!) {
                deleteReport(id: $id) {
                    ok
                    errors
                }
            }
        """

        CREATE_LINK = """
            mutation CreateLink($data: LinkCreateInput!) {
                createLink(data: $data) {
                    ... on LinkTypeMutationResponseType {
                        ok
                        errors
                        result {
                            id
                            title
                            url
                            linkType
                        }
                    }
                }
            }
        """

        UPDATE_LINK = """
            mutation UpdateLink($id: ID!, $data: LinkUpdateInput!) {
                updateLink(id: $id, data: $data) {
                    ... on LinkTypeMutationResponseType {
                        ok
                        errors
                        result {
                            id
                            title
                        }
                    }
                }
            }
        """

        DELETE_LINK = """
            mutation DeleteLink($id: ID!) {
                deleteLink(id: $id) {
                    ok
                    errors
                }
            }
        """

        DELETE_THEMATIC_AREA = """
            mutation DeleteThematicArea($id: ID!) {
                deleteThematicArea(id: $id) {
                    ok
                    errors
                }
            }
        """
        CREATE_REPORT = """
            mutation CreateReport($data: ReportCreateInput!) {
                createReport(data: $data) {
                    ... on ReportTypeMutationResponseType{


                    ok
                    errors
                    result {
                        id
                        title
                        contentType
                        visibility
                        iframeUrl
                    }
                }
            }
        }
        """

        UPDATE_REPORT = """
            mutation UpdateReport($id: ID!, $data: ReportUpdateInput!) {
                updateReport(id: $id, data: $data) {
                    ... on ReportTypeMutationResponseType{


                    ok
                    errors
                    result {
                        id
                        title
                        visibility
                    }
                }
            }
        }
        """

    @typing.override
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = UserFactory.create()
        cls.staff = UserFactory.create(role=User.Role.STAFF)
        cls.thematic_area = ThematicAreaFactory.create()

    def test_create_iframe_report(self):
        self.force_login(self.user)
        with patch("apps.reports.graphql.mutations.trigger_document_extraction") as mock_trigger:
            mock_trigger.return_value = None
            content = self.query_check(
                self.Mutation.CREATE_REPORT,
                variables={
                    "data": {
                        "title": "Test Report",
                        "contentType": Report.ContentType.IFRAME.name,
                        "iframeUrl": "https://app.powerbi.com/embed/123",
                        "thematicArea": str(self.thematic_area.pk),
                        "publishedAt": self.PUBLISHED_AT,
                    },
                },
            )
        resp = content["data"]["createReport"]
        assert resp["ok"] is True
        assert resp["errors"] is None
        assert resp["result"]["title"] == "Test Report"
        assert resp["result"]["contentType"] == Report.ContentType.IFRAME.name
        assert resp["result"]["visibility"] == Report.Visibility.PUBLIC.name
        mock_trigger.assert_called_once()

    def test_create_report_requires_thematic_area_and_published_at(self):
        self.force_login(self.user)
        data = {
            "title": "Missing Required",
            "contentType": Report.ContentType.IFRAME.name,
            "iframeUrl": "https://example.com/embed",
            "thematicArea": str(self.thematic_area.pk),
            "publishedAt": self.PUBLISHED_AT,
        }
        for field in ("thematicArea", "publishedAt"):
            with self.subTest(missing=field):
                content = self.query_check(
                    self.Mutation.CREATE_REPORT,
                    assert_errors=True,
                    variables={"data": {k: v for k, v in data.items() if k != field}},
                )
                assert f"Field '{field}' of required type" in content["errors"][0]["message"]
        assert not Report.objects.filter(title="Missing Required").exists()

    def test_create_report_requires_auth(self):
        self.logout()
        content = self.query_check(
            self.Mutation.CREATE_REPORT,
            variables={
                "data": {
                    "title": "Unauthorized",
                    "contentType": Report.ContentType.IFRAME.name,
                    "iframeUrl": "https://example.com/embed",
                    "thematicArea": str(self.thematic_area.pk),
                    "publishedAt": self.PUBLISHED_AT,
                },
            },
        )
        self.assert_permission_denied(content, "createReport")

    def test_cannot_change_private_to_public(self):
        self.force_login(self.user)
        private_report = ReportFactory.create(
            visibility=Report.Visibility.PRIVATE,
            uploaded_by=self.user,
        )
        content = self.query_check(
            self.Mutation.UPDATE_REPORT,
            variables={
                "id": str(private_report.pk),
                "data": {"visibility": Report.Visibility.PUBLIC.name},
            },
        )
        resp = content["data"]["updateReport"]
        assert resp["ok"] is False
        assert resp["errors"] is not None

    # ------------------------------------------------------------------
    # deleteReport
    # ------------------------------------------------------------------

    def test_authenticated_can_delete_report(self):
        self.force_login(self.user)
        report = ReportFactory.create(uploaded_by=self.user)
        content = self.query_check(
            self.Mutation.DELETE_REPORT,
            variables={"id": self.gID(report.pk)},
        )
        resp = content["data"]["deleteReport"]
        assert resp["ok"] is True
        assert not Report.objects.filter(pk=report.pk).exists()

    def test_unauthenticated_cannot_delete_report(self):
        self.logout()
        report = ReportFactory.create(uploaded_by=self.user)
        content = self.query_check(
            self.Mutation.DELETE_REPORT,
            variables={"id": self.gID(report.pk)},
        )
        self.assert_permission_denied(content, "deleteReport")

    # ------------------------------------------------------------------
    # Document extraction triggered on REPORT-type create
    # ------------------------------------------------------------------

    def test_create_report_type_report_triggers_extraction(self):
        self.force_login(self.user)
        with patch("apps.reports.graphql.mutations.trigger_document_extraction") as mock_trigger:
            mock_trigger.return_value = None
            content = self.query_check(
                self.Mutation.CREATE_REPORT,
                variables={
                    "data": {
                        "title": "AI Report",
                        "contentType": Report.ContentType.IFRAME.name,
                        "iframeUrl": "https://example.com/embed",
                        "thematicArea": str(self.thematic_area.pk),
                        "publishedAt": self.PUBLISHED_AT,
                        "reportType": Report.ReportType.REPORT.name,
                    },
                },
            )
        resp = content["data"]["createReport"]
        assert resp["ok"] is True
        mock_trigger.assert_called_once()
        assert mock_trigger.call_args.kwargs["trigger"] == DocumentExtractionRun.Trigger.REPORT_CREATED

    def test_create_non_report_type_skips_extraction(self):
        self.force_login(self.user)
        with patch("apps.reports.graphql.mutations.trigger_document_extraction") as mock_trigger:
            mock_trigger.return_value = None
            content = self.query_check(
                self.Mutation.CREATE_REPORT,
                variables={
                    "data": {
                        "title": "A Manual",
                        "contentType": Report.ContentType.IFRAME.name,
                        "iframeUrl": "https://example.com/embed",
                        "thematicArea": str(self.thematic_area.pk),
                        "publishedAt": self.PUBLISHED_AT,
                        "reportType": Report.ReportType.MANUAL.name,
                    },
                },
            )
        resp = content["data"]["createReport"]
        assert resp["ok"] is True
        mock_trigger.assert_not_called()

    # ------------------------------------------------------------------
    # createLink / updateLink / deleteLink
    # ------------------------------------------------------------------

    def test_staff_can_create_link(self):
        self.force_login(self.staff)
        content = self.query_check(
            self.Mutation.CREATE_LINK,
            variables={
                "data": {
                    "title": "IFRC GO",
                    "url": "https://go.ifrc.org",
                    "linkType": Link.LinkType.EXTERNAL.name,
                },
            },
        )
        resp = content["data"]["createLink"]
        assert resp["ok"] is True
        assert resp["result"]["title"] == "IFRC GO"
        assert resp["result"]["linkType"] == Link.LinkType.EXTERNAL.name

    def test_viewer_cannot_create_link(self):
        self.force_login(self.user)
        content = self.query_check(
            self.Mutation.CREATE_LINK,
            variables={
                "data": {
                    "title": "Blocked",
                    "url": "https://example.com",
                    "linkType": Link.LinkType.EXTERNAL.name,
                },
            },
        )
        self.assert_permission_denied(content, "createLink")

    def test_staff_can_update_link(self):
        self.force_login(self.staff)
        link = LinkFactory.create()
        content = self.query_check(
            self.Mutation.UPDATE_LINK,
            variables={"id": self.gID(link.pk), "data": {"title": "Updated Title"}},
        )
        resp = content["data"]["updateLink"]
        assert resp["ok"] is True
        assert resp["result"]["title"] == "Updated Title"

    def test_staff_can_delete_link(self):
        self.force_login(self.staff)
        link = LinkFactory.create()
        content = self.query_check(
            self.Mutation.DELETE_LINK,
            variables={"id": self.gID(link.pk)},
        )
        resp = content["data"]["deleteLink"]
        assert resp["ok"] is True
        assert not Link.objects.filter(pk=link.pk).exists()

    def test_viewer_cannot_delete_link(self):
        self.force_login(self.user)
        link = LinkFactory.create()
        content = self.query_check(
            self.Mutation.DELETE_LINK,
            variables={"id": self.gID(link.pk)},
        )
        self.assert_permission_denied(content, "deleteLink")
        assert Link.objects.filter(pk=link.pk).exists()

    def test_staff_can_delete_unused_thematic_area(self):
        self.force_login(self.staff)
        thematic_area = ThematicAreaFactory.create(name="Unused Area")
        content = self.query_check(
            self.Mutation.DELETE_THEMATIC_AREA,
            variables={"id": self.gID(thematic_area.pk)},
        )
        resp = content["data"]["deleteThematicArea"]
        assert resp["ok"] is True, resp
        assert not ThematicArea.objects.filter(pk=thematic_area.pk).exists()

    def test_cannot_delete_thematic_area_used_by_reports(self):
        self.force_login(self.staff)
        thematic_area = ThematicAreaFactory.create(name="In Use Area")
        ReportFactory.create_batch(2, thematic_area=thematic_area, uploaded_by=self.staff)
        content = self.query_check(
            self.Mutation.DELETE_THEMATIC_AREA,
            variables={"id": self.gID(thematic_area.pk)},
        )
        resp = content["data"]["deleteThematicArea"]
        assert resp["ok"] is False, resp
        assert ThematicArea.objects.filter(pk=thematic_area.pk).exists()

    def test_deleting_missing_report_is_reported_on_the_payload(self):
        self.force_login(self.staff)
        report = ReportFactory.create(uploaded_by=self.staff)
        report_id = self.gID(report.pk)
        report.delete()
        content = self.query_check(
            self.Mutation.DELETE_REPORT,
            variables={"id": report_id},
        )
        resp = content["data"]["deleteReport"]
        assert resp["ok"] is False, resp
