import typing

from apps.gallery.factories import GalleryAlbumFactory
from apps.users.factories import UserFactory
from main.tests import TestCase


class TestGalleryQueries(TestCase):
    class Query:
        ALBUMS = """
            query GalleryAlbums($pagination: OffsetPaginationInput) {
                galleryAlbums(pagination: $pagination, ordering: {createdAt: DESC}) {
                    totalCount
                    pageInfo { offset limit }
                    results {
                        id
                        title
                        description
                        createdBy { id email fullName }
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
        cls.album1 = GalleryAlbumFactory.create(title="Field Trip", created_by=cls.user)
        cls.album2 = GalleryAlbumFactory.create(title="Training Day", created_by=cls.user)

    def test_albums_require_auth(self):
        self.logout()
        content = self.query_check(
            self.Query.ALBUMS,
            assert_errors=True,
            variables={"pagination": {"limit": 10, "offset": 0}},
        )
        assert "errors" in content

    def test_albums_authenticated(self):
        self.force_login(self.user)
        content = self.query_check(
            self.Query.ALBUMS,
            variables={"pagination": {"limit": 10, "offset": 0}},
        )
        assert content["data"]["galleryAlbums"]["totalCount"] == 2
