import typing

from apps.geo.factories import CountryFactory, RegionFactory
from apps.geo.models import AdminArea
from main.tests import TestCase


class TestAdminAreaQueries(TestCase):
    class Query:
        ADMIN_AREAS = """
            query AdminAreas($pagination: OffsetPaginationInput, $filters: AdminAreaFilter) {
                adminAreas(pagination: $pagination, filters: $filters, ordering: {name: ASC}) {
                    totalCount
                    pageInfo { offset limit }
                    results {
                        id
                        name
                        nameAm
                        level
                        parentId
                        pcode
                        centroidLat
                        centroidLon
                    }
                }
            }
        """

    @typing.override
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.country = CountryFactory.create(name="Ethiopia", pcode="ET")
        cls.region = RegionFactory.create(name="Oromia", parent=cls.country, pcode="ET-OR")

    def test_admin_areas_query(self):
        content = self.query_check(
            self.Query.ADMIN_AREAS,
            variables={"pagination": {"limit": 10, "offset": 0}},
        )
        assert content["data"]["adminAreas"]["totalCount"] == 2

    def test_filter_by_level(self):
        content = self.query_check(
            self.Query.ADMIN_AREAS,
            variables={
                "pagination": {"limit": 10, "offset": 0},
                "filters": {"level": AdminArea.Level.REGION.name},
            },
        )
        results = content["data"]["adminAreas"]["results"]
        assert len(results) == 1
        assert results[0]["name"] == "Oromia"
        assert results[0]["level"] == AdminArea.Level.REGION.name

    def test_filter_by_pcode(self):
        content = self.query_check(
            self.Query.ADMIN_AREAS,
            variables={
                "pagination": {"limit": 10, "offset": 0},
                "filters": {"pcode": "ET"},
            },
        )
        results = content["data"]["adminAreas"]["results"]
        assert len(results) == 1
        assert results[0]["name"] == "Ethiopia"
