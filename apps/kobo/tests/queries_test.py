import datetime
import typing

from apps.kobo.factories import KoboSubmissionFactory
from apps.kobo.models import KoboForm, KoboSyncState
from main.tests import TestCase


class TestKoboStatsQuery(TestCase):
    class Query:
        KOBO_STATS = """
            query KoboStats {
                koboStats {
                    generatedAt
                    alert {
                        source { form formLabel assetUid lastFetchedAt confirmedRecords }
                        totalEmergencies
                        peopleAffected
                        peopleDisplaced
                        byHazard { key count }
                        byRegion { key count }
                    }
                    rapidNeeds { totalAssessments peopleInNeed }
                    field { totalReports peopleReached }
                }
            }
        """

    @typing.override
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Two confirmed alerts (distinct emergencies) + one unapproved (excluded).
        KoboSubmissionFactory.create(
            form=KoboForm.EMERGENCY_ALERT,
            emergency_code="EM-A",
            raw={
                "context/hazard": "flood",
                "geo/region-one": "Oromia",
                "ppl_impact_group/ppl_affected": "1000",
                "ppl_impact_group/ppl_affected_displaced": "100",
                "emergency_code/unique_code": "EM-A",
            },
        )
        KoboSubmissionFactory.create(
            form=KoboForm.EMERGENCY_ALERT,
            emergency_code="EM-B",
            raw={
                "context/hazard": "flood",
                "geo/region-one": "Tigray",
                "ppl_impact_group/ppl_affected": "500",
                "ppl_impact_group/ppl_affected_displaced": "50",
                "emergency_code/unique_code": "EM-B",
            },
        )
        KoboSubmissionFactory.create(
            form=KoboForm.EMERGENCY_ALERT,
            validation_status="validation_status_not_approved",
            emergency_code="EM-C",
            raw={"ppl_impact_group/ppl_affected": "9999", "emergency_code/unique_code": "EM-C"},
        )
        KoboSyncState.objects.create(
            form=KoboForm.EMERGENCY_ALERT,
            asset_uid="aydYC8AYCDuX7y4PwfvgrX",
            last_fetched_at=datetime.datetime(2026, 8, 27, tzinfo=datetime.UTC),
            last_status=KoboSyncState.Status.SUCCESS,
            record_count=3,
        )

    def test_kobo_stats(self):
        content = self.query_check(self.Query.KOBO_STATS)
        alert = content["data"]["koboStats"]["alert"]

        # Only the two approved submissions are counted.
        assert alert["totalEmergencies"] == 2
        assert alert["peopleAffected"] == 1500
        assert alert["peopleDisplaced"] == 150
        assert alert["source"]["confirmedRecords"] == 2
        assert alert["source"]["lastFetchedAt"] is not None
        assert {b["key"]: b["count"] for b in alert["byHazard"]} == {"flood": 2}
        assert {b["key"]: b["count"] for b in alert["byRegion"]} == {"Oromia": 1, "Tigray": 1}


class TestFieldReachedSum(TestCase):
    """People Reached is summed across all field reports: each report is a distinct
    reporting period / response action, so they are not assumed to reach the same
    people (unlike the mobilized-resource figures, which stay deduped per branch).
    """

    def _make(self, code: str, branch: str, reach: int):
        KoboSubmissionFactory.create(
            form=KoboForm.EMERGENCY_FIELD,
            asset_uid="aby6sxp4DyEiohs4XMn7Mu",
            emergency_code=code,
            raw={
                "location/alert_code": code,
                "context/reporting_branch": branch,
                "branch_sitrep/reached_population/g_reach": str(reach),
            },
        )

    def test_people_reached_is_summed(self):
        from apps.kobo.stats import build_kobo_stats

        # Same (code, branch) reported twice -> both count (distinct periods).
        self._make("EM-1", "B1", 100)
        self._make("EM-1", "B1", 300)
        self._make("EM-1", "B2", 50)
        self._make("EM-2", "B1", 200)

        stats = build_kobo_stats()
        # 100 + 300 + 50 + 200 = 650
        assert stats.field.people_reached == 650
        assert stats.field.total_reports == 4


class TestStatsWindow(TestCase):
    """Headline stats only count submissions from the last 6 months."""

    def test_old_submissions_are_excluded(self):
        import datetime

        from django.utils import timezone

        from apps.kobo.stats import build_kobo_stats

        recent = timezone.now() - datetime.timedelta(days=30)
        old = timezone.now() - datetime.timedelta(days=300)
        KoboSubmissionFactory.create(
            form=KoboForm.EMERGENCY_ALERT,
            emergency_code="EM-RECENT",
            submission_time=recent,
            raw={"ppl_impact_group/ppl_affected": "1000", "emergency_code/unique_code": "EM-RECENT"},
        )
        KoboSubmissionFactory.create(
            form=KoboForm.EMERGENCY_ALERT,
            emergency_code="EM-OLD",
            submission_time=old,
            raw={"ppl_impact_group/ppl_affected": "9999", "emergency_code/unique_code": "EM-OLD"},
        )

        stats = build_kobo_stats()
        # Only the recent alert is in the window.
        assert stats.alert.total_emergencies == 1
        assert stats.alert.people_affected == 1000


class TestStatsDateRange(TestCase):
    """An explicit date range replaces the default 6-month window (inclusive, open-ended)."""

    class Query:
        KOBO_STATS = """
            query KoboStats($startDate: Date, $endDate: Date) {
                koboStats(startDate: $startDate, endDate: $endDate) {
                    alert { totalEmergencies peopleAffected }
                }
            }
        """

    @typing.override
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for code, day, affected in [
            ("EM-JAN", datetime.datetime(2025, 1, 15, 10, tzinfo=datetime.UTC), "100"),
            ("EM-MAR", datetime.datetime(2025, 3, 31, 10, tzinfo=datetime.UTC), "200"),
            ("EM-JUN", datetime.datetime(2025, 6, 1, 10, tzinfo=datetime.UTC), "400"),
        ]:
            KoboSubmissionFactory.create(
                form=KoboForm.EMERGENCY_ALERT,
                emergency_code=code,
                submission_time=day,
                raw={"ppl_impact_group/ppl_affected": affected, "emergency_code/unique_code": code},
            )

    def _alert(self, **variables):
        content = self.query_check(self.Query.KOBO_STATS, variables=variables)
        return content["data"]["koboStats"]["alert"]

    def test_bounded_range_is_inclusive(self):
        alert = self._alert(startDate="2025-01-15", endDate="2025-03-31")
        assert alert["totalEmergencies"] == 2
        assert alert["peopleAffected"] == 300

    def test_open_ended_ranges(self):
        assert self._alert(startDate="2025-02-01")["peopleAffected"] == 600
        assert self._alert(endDate="2025-02-01")["peopleAffected"] == 100

    def test_same_day_range_is_valid(self):
        assert self._alert(startDate="2025-03-31", endDate="2025-03-31")["peopleAffected"] == 200

    def test_reversed_range_is_rejected(self):
        content = self.query_check(
            self.Query.KOBO_STATS,
            assert_errors=True,
            variables={"startDate": "2025-03-31", "endDate": "2025-01-15"},
        )
        (error,) = content["errors"]
        assert error["message"] == "startDate must be on or before endDate."
        assert error["extensions"]["code"] == "INVALID_DATE_RANGE"
        assert content["data"] is None

    def test_explicit_range_ignores_default_window(self):
        # All three are well over 6 months old, so only an explicit range sees them.
        assert self._alert()["totalEmergencies"] == 0
        assert self._alert(startDate="2024-01-01")["totalEmergencies"] == 3


class TestFieldResourceDedup(TestCase):
    """Mobilized resources are restated in every periodic sitrep, so they get the
    same per-(emergency, branch) treatment as People Reached.
    """

    def _make(self, code: str, branch: str, **raw: str):
        KoboSubmissionFactory.create(
            form=KoboForm.EMERGENCY_FIELD,
            asset_uid="aby6sxp4DyEiohs4XMn7Mu",
            emergency_code=code,
            raw={"context/reporting_branch": branch, **raw},
        )

    def test_resources_are_not_summed_across_periods(self):
        from apps.kobo.stats import build_kobo_stats

        # One branch, two reporting periods, the same standing figures.
        for _ in range(2):
            self._make(
                "EM-1",
                "B1",
                **{
                    "branch_sitrep/resources_group/resources_staff": "8",
                    "branch_sitrep/resources_group/resources_volunteers": "3",
                    "branch_sitrep/resources_group/resources_BDRT": "7",
                },
            )
        # A second branch is additive.
        self._make("EM-1", "B2", **{"branch_sitrep/resources_group/resources_staff": "2"})

        stats = build_kobo_stats()
        assert stats.field.staff_mobilized == 10  # 8 + 2, not 8 + 8 + 2
        assert stats.field.volunteers_mobilized == 3
        assert stats.field.bdrt_mobilized == 7

    def test_support_requested_reads_support_required(self):
        """``support_required`` is a select_multiple, not a yes/no."""
        from apps.kobo.stats import build_kobo_stats

        # Same branch asks in both of its sitreps -> counted once.
        for _ in range(2):
            self._make("EM-1", "B1", **{"branch_sitrep/resources_group/support_required": "relief_nfi coordination"})
        self._make("EM-1", "B2", **{"branch_sitrep/resources_group/support_required": "allocation_funds_response"})
        # Nothing requested.
        self._make("EM-2", "B3", **{"branch_sitrep/resources_group/support_required": ""})

        assert build_kobo_stats().field.support_requested == 2


class TestKoboEmergencyDetailQuery(TestCase):
    """`koboEmergency(id)` returns the alert detail joined with the RNA and Field
    reports that share its emergency code, numbered in submission order.
    """

    class Query:
        KOBO_EMERGENCY = """
            query KoboEmergency($id: ID!) {
                koboEmergency(id: $id) {
                    id
                    emergencyCode
                    title
                    hazard
                    region
                    zone
                    latitude
                    longitude
                    populationInAffectedArea
                    peopleAffected
                    peopleDisplaced
                    rapidNeeds { label value }
                    fieldReports { label value }
                }
            }
        """

    def test_detail_joins_related_reports(self):
        import datetime

        code = "EM-20260815-flood-Tigray-zone"
        alert = KoboSubmissionFactory.create(
            form=KoboForm.EMERGENCY_ALERT,
            emergency_code=code,
            raw={
                "emergency_code/unique_code": code,
                "context/hazard": "flood",
                "geo/region-one": "Tigray",
                "geo/zone-multiple": "Central Eastern",
                "geo/location_scope": "zone",
                "ppl_impact_group/ppl_before": "282652",
                "ppl_impact_group/ppl_affected": "41836",
                "ppl_impact_group/ppl_affected_displaced": "120",
                "_geolocation": [14.076213, 38.79844],
            },
        )
        # Two RNAs sharing the code, submitted in order.
        for i, (day, in_need) in enumerate(((10, "5000"), (12, "3000")), start=1):
            KoboSubmissionFactory.create(
                form=KoboForm.RAPID_NEEDS_ASSESSMENT,
                asset_uid="aPuV7tDb9mdRiK8hUhkxJC",
                emergency_code=code,
                submission_time=datetime.datetime(2026, 8, day, tzinfo=datetime.UTC),
                raw={"ppl_impact_group/ppl_in_need": in_need, "location/woreda": f"Woreda_{i}"},
            )
        # One field report, and one unrelated RNA that must NOT appear.
        KoboSubmissionFactory.create(
            form=KoboForm.EMERGENCY_FIELD,
            asset_uid="aby6sxp4DyEiohs4XMn7Mu",
            emergency_code=code,
            raw={"branch_sitrep/reached_population/g_reach": "1800"},
        )
        KoboSubmissionFactory.create(
            form=KoboForm.RAPID_NEEDS_ASSESSMENT,
            asset_uid="aPuV7tDb9mdRiK8hUhkxJC",
            emergency_code="EM-OTHER",
            raw={"ppl_impact_group/ppl_in_need": "99999"},
        )

        content = self.query_check(self.Query.KOBO_EMERGENCY, variables={"id": str(alert.id)})
        detail = content["data"]["koboEmergency"]

        assert detail["title"] == "Flood — Central Eastern, Tigray"
        assert detail["region"] == "Tigray"
        assert detail["zone"] == "Central Eastern"
        assert detail["populationInAffectedArea"] == 282652
        assert detail["peopleAffected"] == 41836
        assert detail["latitude"] == 14.076213
        assert detail["longitude"] == 38.79844
        assert [r["value"] for r in detail["rapidNeeds"]] == [5000, 3000]
        assert detail["rapidNeeds"][0]["label"] == f"{code} — RNA #1 (Woreda 1)"
        assert [r["value"] for r in detail["fieldReports"]] == [1800]

    def test_unknown_id_returns_null(self):
        content = self.query_check(
            self.Query.KOBO_EMERGENCY,
            variables={"id": "00000000-0000-0000-0000-000000000000"},
        )
        assert content["data"]["koboEmergency"] is None


class TestLabelResolver(TestCase):
    """`build_label_maps` + `FormLabels` turn Kobo choice codes into labels."""

    CONTENT = {
        "survey": [
            {"type": "select_one", "name": "modality1", "select_from_list_name": "modality"},
            {"type": "select_multiple", "name": "action_taken", "select_from_list_name": "action"},
            {"type": "text", "name": "notes"},
        ],
        "choices": [
            {"list_name": "modality", "name": "Modality2", "label": ["Cash and Voucher Assistance (CVA)", None]},
            {"list_name": "action", "name": "water_dist", "label": ["Distribution of water", None]},
            {"list_name": "action", "name": "hygiene", "label": "Hygiene promotion"},
        ],
    }

    def test_resolution(self):
        from apps.kobo.labels import FormLabels, build_label_maps

        maps = build_label_maps(self.CONTENT)
        labels = FormLabels(choices=maps["choices"], fields=maps["fields"])

        # select_one -> single label
        assert labels.resolve_one("context/modality1", "Modality2") == "Cash and Voucher Assistance (CVA)"
        # select_multiple -> space-split, each resolved (list + bare-string labels both work)
        assert labels.resolve_many("branch_sitrep/action_taken", "water_dist hygiene") == [
            "Distribution of water",
            "Hygiene promotion",
        ]
        # unknown code -> humanized fallback, not dropped
        assert labels.resolve_many("branch_sitrep/action_taken", "unmapped_code") == ["unmapped code"]
        # not a select field -> humanized
        assert labels.resolve_one("group/notes", "some_value") == "some value"


class TestKoboReportDetailQueries(TestCase):
    """`koboRapidNeeds`/`koboFieldReport` return full detail with resolved chips."""

    class Query:
        RNA = """
            query R($id: ID!) {
                koboRapidNeeds(id: $id) {
                    index title region zone woreda reportingBranch
                    peopleInNeed peopleAffectedNonDisplaced
                    topAffectedGroups prioritySectors vulnerableGroups responseModalities
                }
            }
        """
        FIELD = """
            query F($id: ID!) {
                koboFieldReport(id: $id) {
                    index title reportingBranch location
                    reportingPeriodStart reportingPeriodEnd reportingDays
                    peopleReached volunteers staff bdrt
                    typeOfReportedInformation prepositionedStocksUsed responseActions latestDevelopments
                }
            }
        """

    @staticmethod
    def _schema(
        form: KoboForm,
        choices: dict[str, dict[str, str]],
        fields: dict[str, dict[str, typing.Any]],
    ) -> None:
        from apps.kobo.models import KoboFormSchema

        KoboFormSchema.objects.create(
            form=form,
            asset_uid="x",
            labels={"choices": choices, "fields": fields},
        )

    def test_rapid_needs_detail(self):
        from apps.kobo.models import KoboForm

        code = "EM-1"
        self._schema(
            KoboForm.RAPID_NEEDS_ASSESSMENT,
            {"sector": {"food": "Food"}, "modality": {"Modality2": "Cash and Voucher Assistance (CVA)"}},
            {"sector1": {"list": "sector", "multiple": False}, "modality1": {"list": "modality", "multiple": False}},
        )
        rna = KoboSubmissionFactory.create(
            form=KoboForm.RAPID_NEEDS_ASSESSMENT,
            asset_uid="aPuV7tDb9mdRiK8hUhkxJC",
            emergency_code=code,
            raw={
                "location/region": "Somali",
                "location/woreda": "Kebridehar",
                "ppl_impact_group/ppl_in_need": "74000",
                "ppl_impact_group/ppl_affected_non-displaced": "108200",
                "priority_sectors/sector1": "food",
                "response_modalities/modality1": "Modality2",
            },
        )
        content = self.query_check(self.Query.RNA, variables={"id": str(rna.id)})
        detail = content["data"]["koboRapidNeeds"]
        assert detail["index"] == 1
        assert detail["title"] == f"{code} — RNA #1 (Kebridehar)"
        assert detail["peopleInNeed"] == 74000
        assert detail["peopleAffectedNonDisplaced"] == 108200
        assert detail["prioritySectors"] == ["Food"]
        assert detail["responseModalities"] == ["Cash and Voucher Assistance (CVA)"]

    def test_field_report_detail_branch_from_alert(self):
        from apps.kobo.models import KoboForm

        code = "EM-FR"
        self._schema(
            KoboForm.EMERGENCY_FIELD,
            {"action": {"water_dist": "Distribution of water", "assessment_ercs": "Assessment (ERCS)"}},
            {"action_taken": {"list": "action", "multiple": True}},
        )
        # Parent alert supplies the branch (region) name.
        KoboSubmissionFactory.create(
            form=KoboForm.EMERGENCY_ALERT,
            emergency_code=code,
            raw={"geo/region-one": "Somali", "emergency_code/unique_code": code},
        )
        field = KoboSubmissionFactory.create(
            form=KoboForm.EMERGENCY_FIELD,
            asset_uid="aby6sxp4DyEiohs4XMn7Mu",
            emergency_code=code,
            raw={
                "location/region-one": "Somali",
                "context/period-start_date": "2026-08-01",
                "context/period-end_date": "2026-08-28",
                "context/reporting_days": "28",
                "branch_sitrep/reached_population/g_reach": "18400",
                "branch_sitrep/resources_group/resources_volunteers": "120",
                "branch_sitrep/action_taken": "assessment_ercs water_dist",
                "latest_info/third_party_sources": "local_admin",
                "latest_info/info_primary-source": "Early action activities in Korahe zone.",
            },
        )
        content = self.query_check(self.Query.FIELD, variables={"id": str(field.id)})
        detail = content["data"]["koboFieldReport"]
        assert detail["title"] == f"{code} — Field Report #1"
        assert detail["reportingBranch"] == "Somali"  # from the alert, not the RE-code
        assert detail["peopleReached"] == 18400
        assert detail["reportingDays"] == 28
        assert detail["responseActions"] == ["Assessment (ERCS)", "Distribution of water"]
        assert detail["typeOfReportedInformation"] == "ERCS field teams and third-party sources"
        assert detail["latestDevelopments"] == "Early action activities in Korahe zone."
