import typing

from apps.content.factories import NewsPostFactory
from apps.users.factories import UserFactory
from main.tests import TestCase


class TestNewsPostQueries(TestCase):
    class Query:
        NEWS_POSTS = """
            query NewsPosts($pagination: OffsetPaginationInput, $filters: NewsPostFilter) {
                newsPosts(pagination: $pagination, filters: $filters, ordering: {createdAt: DESC}) {
                    totalCount
                    pageInfo { offset limit }
                    results {
                        id
                        title
                        description
                        isPublished
                        publishedAt
                        authorId
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
        cls.draft = NewsPostFactory.create(title="Draft Post", is_published=False, author=cls.user)
        cls.published = NewsPostFactory.create(title="Published Post", is_published=True, author=cls.user)

    def test_news_posts_query(self):
        content = self.query_check(
            self.Query.NEWS_POSTS,
            variables={"pagination": {"limit": 10, "offset": 0}},
        )
        assert content["data"]["newsPosts"]["totalCount"] == 2

    def test_filter_published(self):
        content = self.query_check(
            self.Query.NEWS_POSTS,
            variables={
                "pagination": {"limit": 10, "offset": 0},
                "filters": {"isPublished": True},
            },
        )
        results = content["data"]["newsPosts"]["results"]
        assert len(results) == 1
        assert results[0]["title"] == "Published Post"
        assert results[0]["publishedAt"] is not None
