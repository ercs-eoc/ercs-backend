import typing

from apps.emergency.factories import EmergencyFactory
from main.tests import TestCase


class TestEmergencyQueries(TestCase):
    class Query:
        EMERGENCIES = """
            query Emergencies($pagination: OffsetPaginationInput) {
                emergencies(pagination: $pagination, ordering: {startDate: DESC}) {
                    totalCount
                    pageInfo { offset limit }
                    results {
                        id
                        goId
                        name
                        disasterType
                        status
                        startDate
                        affectedPop
                        goUrl
                        syncedAt
                    }
                }
            }
        """

    @typing.override
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.em1 = EmergencyFactory.create(name="Oromia Flood", disaster_type="Flood")
        cls.em2 = EmergencyFactory.create(name="Tigray Drought", disaster_type="Drought")

    def test_emergencies_query(self):
        content = self.query_check(
            self.Query.EMERGENCIES,
            variables={"pagination": {"limit": 10, "offset": 0}},
        )
        data = content["data"]["emergencies"]
        assert data["totalCount"] == 2

    def test_filter_by_disaster_type(self):
        content = self.query_check(
            self.Query.EMERGENCIES,
            variables={
                "pagination": {"limit": 10, "offset": 0},
            },
        )
        assert content["data"]["emergencies"]["totalCount"] == 2
