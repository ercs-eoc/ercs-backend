import typing

from apps.teams.factories import TeamFactory
from apps.users.factories import UserFactory
from main.tests import TestCase


class TestTeamQueries(TestCase):
    class Query:
        TEAMS = """
            query Teams($pagination: OffsetPaginationInput) {
                teams(pagination: $pagination, ordering: {name: ASC}) {
                    totalCount
                    pageInfo { offset limit }
                    results {
                        id
                        name
                        description
                        createdAt
                    }
                }
            }
        """

    @typing.override
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = UserFactory.create()
        cls.team1 = TeamFactory.create(name="Alpha BDRT")
        cls.team2 = TeamFactory.create(name="Beta CBHFA")

    def test_teams_require_auth(self):
        self.logout()
        content = self.query_check(
            self.Query.TEAMS,
            assert_errors=True,
            variables={"pagination": {"limit": 10, "offset": 0}},
        )
        assert "errors" in content

    def test_teams_query_authenticated(self):
        self.force_login(self.user)
        content = self.query_check(
            self.Query.TEAMS,
            variables={"pagination": {"limit": 10, "offset": 0}},
        )
        assert content["data"]["teams"]["totalCount"] == 2
