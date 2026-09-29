import io
import typing

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.gallery.factories import GalleryAlbumFactory, GalleryImageFactory
from apps.gallery.graphql.mutations import MAX_BULK_GALLERY_IMAGES, MAX_GALLERY_ALBUM_IMAGES
from apps.gallery.models import GalleryAlbum, GalleryImage
from apps.users.factories import UserFactory
from apps.users.models import User
from main.tests import TestCase


def png_upload(name: str = "image.png") -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (1, 1)).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class TestGalleryMutations(TestCase):
    class Mutation:
        BULK_CREATE_GALLERY_IMAGES = """
            mutation BulkCreateGalleryImages($data: GalleryImageBulkCreateInput!) {
                bulkCreateGalleryImages(data: $data) {
                    ... on GalleryImageTypeListMutationResponseType {
                        ok
                        errors
                        result {
                            id
                            caption
                            order
                        }
                    }
                }
            }
        """

        DELETE_GALLERY_ALBUM = """
            mutation DeleteGalleryAlbum($id: ID!) {
                deleteGalleryAlbum(id: $id) {
                    ok
                    errors
                }
            }
        """

        DELETE_GALLERY_IMAGE = """
            mutation DeleteGalleryImage($id: ID!) {
                deleteGalleryImage(id: $id) {
                    ok
                    errors
                }
            }
        """

    @typing.override
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.staff = UserFactory.create(role=User.Role.STAFF)

    def _bulk_create_images(self, album: GalleryAlbum, count: int) -> dict[str, typing.Any]:
        images = [{"album": str(album.pk), "image": None, "caption": f"Caption {i}", "order": i} for i in range(count)]
        return self.query_check(
            self.Mutation.BULK_CREATE_GALLERY_IMAGES,
            variables={"data": {"images": images}},
            files={str(i): png_upload(f"image-{i}.png") for i in range(count)},
            map={str(i): [f"variables.data.images.{i}.image"] for i in range(count)},
        )

    def test_bulk_create_gallery_images(self):
        self.force_login(self.staff)
        album = GalleryAlbumFactory.create()
        resp = self._bulk_create_images(album, 3)["data"]["bulkCreateGalleryImages"]
        assert resp["ok"] is True, resp
        assert [image["order"] for image in resp["result"]] == [0, 1, 2]
        assert GalleryImage.objects.filter(album=album).count() == 3

    def test_bulk_create_gallery_images_over_limit_fails(self):
        self.force_login(self.staff)
        album = GalleryAlbumFactory.create()
        resp = self._bulk_create_images(album, MAX_BULK_GALLERY_IMAGES + 1)["data"]["bulkCreateGalleryImages"]
        assert resp["ok"] is False, resp
        assert not GalleryImage.objects.filter(album=album).exists()

    def test_bulk_create_gallery_images_over_album_limit_fails(self):
        self.force_login(self.staff)
        album = GalleryAlbumFactory.create()
        GalleryImageFactory.create_batch(MAX_GALLERY_ALBUM_IMAGES - 1, album=album)
        resp = self._bulk_create_images(album, 2)["data"]["bulkCreateGalleryImages"]
        assert resp["ok"] is False, resp
        assert GalleryImage.objects.filter(album=album).count() == MAX_GALLERY_ALBUM_IMAGES - 1

        resp = self._bulk_create_images(album, 1)["data"]["bulkCreateGalleryImages"]
        assert resp["ok"] is True, resp
        assert GalleryImage.objects.filter(album=album).count() == MAX_GALLERY_ALBUM_IMAGES

    def test_bulk_create_gallery_images_empty_list_fails(self):
        self.force_login(self.staff)
        content = self.query_check(
            self.Mutation.BULK_CREATE_GALLERY_IMAGES,
            variables={"data": {"images": []}},
        )
        resp = content["data"]["bulkCreateGalleryImages"]
        assert resp["ok"] is False, resp

    def test_bulk_create_gallery_images_is_atomic(self):
        self.force_login(self.staff)
        album = GalleryAlbumFactory.create()
        images = [
            {"album": str(album.pk), "image": None},
            {"album": str(album.pk), "image": None},
        ]
        content = self.query_check(
            self.Mutation.BULK_CREATE_GALLERY_IMAGES,
            variables={"data": {"images": images}},
            files={
                "0": png_upload(),
                "1": SimpleUploadedFile("bad.png", b"not an image", content_type="image/png"),
            },
            map={"0": ["variables.data.images.0.image"], "1": ["variables.data.images.1.image"]},
        )
        resp = content["data"]["bulkCreateGalleryImages"]
        assert resp["ok"] is False, resp
        assert not GalleryImage.objects.filter(album=album).exists()

    def test_unauthenticated_cannot_bulk_create_gallery_images(self):
        self.logout()
        album = GalleryAlbumFactory.create()
        content = self._bulk_create_images(album, 1)
        self.assert_permission_denied(content, "bulkCreateGalleryImages")
        assert not GalleryImage.objects.filter(album=album).exists()

    def test_delete_gallery_image(self):
        self.force_login(self.staff)
        image = GalleryImageFactory.create()
        content = self.query_check(
            self.Mutation.DELETE_GALLERY_IMAGE,
            variables={"id": str(image.pk)},
        )
        resp = content["data"]["deleteGalleryImage"]
        assert resp["ok"] is True, resp
        assert not GalleryImage.objects.filter(pk=image.pk).exists()

    def test_delete_gallery_album_cascades_to_images(self):
        self.force_login(self.staff)
        album = GalleryAlbumFactory.create()
        GalleryImageFactory.create_batch(2, album=album)
        content = self.query_check(
            self.Mutation.DELETE_GALLERY_ALBUM,
            variables={"id": str(album.pk)},
        )
        resp = content["data"]["deleteGalleryAlbum"]
        assert resp["ok"] is True, resp
        assert not GalleryAlbum.objects.filter(pk=album.pk).exists()
        assert not GalleryImage.objects.filter(album_id=album.pk).exists()

    def test_unauthenticated_cannot_delete_gallery_album(self):
        self.logout()
        album = GalleryAlbumFactory.create()
        content = self.query_check(
            self.Mutation.DELETE_GALLERY_ALBUM,
            variables={"id": str(album.pk)},
        )
        self.assert_permission_denied(content, "deleteGalleryAlbum")
        assert GalleryAlbum.objects.filter(pk=album.pk).exists()

    def test_deleting_missing_gallery_album_is_reported_on_the_payload(self):
        self.force_login(self.staff)
        album = GalleryAlbumFactory.create()
        album_id = str(album.pk)
        album.delete()
        content = self.query_check(
            self.Mutation.DELETE_GALLERY_ALBUM,
            variables={"id": album_id},
        )
        resp = content["data"]["deleteGalleryAlbum"]
        assert resp["ok"] is False, resp
        assert resp["errors"][0]["messages"] == "This Gallery Album no longer exists. It may already have been deleted."
