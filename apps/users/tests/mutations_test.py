import typing

from apps.geo.factories import AdminAreaFactory
from apps.geo.models import AdminAreaLevel
from apps.users.factories import UserFactory
from apps.users.models import User
from main.tests import TestCase


class TestUserMutations(TestCase):
    class Mutation:
        CREATE_USER = """
            mutation CreateUser($data: UserCreateInput!) {
                createUser(data: $data) {
                    ... on UserTypeMutationResponseType {
                        ok
                        errors
                        result {
                            id
                            email
                            fullName
                            role
                            isActive
                        }
                    }
                }
            }
        """

        UPDATE_USER = """
            mutation UpdateUser($id: ID!, $data: UserUpdateInput!) {
                updateUser(id: $id, data: $data) {
                    ... on UserTypeMutationResponseType {
                        ok
                        errors
                        result {
                            id
                            email
                            fullName
                            role
                            isActive
                        }
                    }
                }
            }
        """

        DELETE_USER = """
            mutation DeleteUser($id: ID!) {
                deleteUser(id: $id) {
                    ok
                    errors
                }
            }
        """

        RESET_USER_PASSWORD = """
            mutation ResetUserPassword($id: ID!, $newPassword: String!) {
                resetUserPassword(id: $id, newPassword: $newPassword) {
                    ... on UserTypeMutationResponseType {
                        ok
                        errors
                    }
                }
            }
        """

        UPDATE_MY_PASSWORD = """
            mutation UpdateMyPassword($data: PasswordUpdateInput!) {
                updateMyPassword(data: $data) {
                    ... on UserTypeMutationResponseType {
                        ok
                        errors
                    }
                }
            }
        """

        LOGIN = """
            mutation Login($email: String!, $password: String!) {
                login(email: $email, password: $password) {
                    id
                    email
                    role
                }
            }
        """

    @typing.override
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.hq_admin = UserFactory.create(role=User.Role.HQ_ADMIN)
        cls.staff = UserFactory.create(role=User.Role.STAFF)
        cls.viewer = UserFactory.create(role=User.Role.VIEWER)

    # ------------------------------------------------------------------
    # login
    # ------------------------------------------------------------------

    def test_login_valid_credentials(self):
        user = UserFactory.create(role=User.Role.STAFF, password="correcthorsebattery")
        content = self.query_check(
            self.Mutation.LOGIN,
            variables={"email": user.email, "password": "correcthorsebattery"},
        )
        result = content["data"]["login"]
        assert result["email"] == user.email
        assert result["role"] == User.Role.STAFF.name

    def test_login_invalid_credentials(self):
        self.query_check(
            self.Mutation.LOGIN,
            assert_errors=True,
            variables={"email": "nobody@ercs.org", "password": "wrongpassword"},
        )

    # ------------------------------------------------------------------
    # createUser
    # ------------------------------------------------------------------

    def test_hq_admin_can_create_user(self):
        self.force_login(self.hq_admin)
        content = self.query_check(
            self.Mutation.CREATE_USER,
            variables={
                "data": {
                    "email": "newstaff@ercs.org",
                    "fullName": "New Staff",
                    "password": "securepassword123",
                    "role": User.Role.STAFF.name,
                },
            },
        )
        resp = content["data"]["createUser"]
        assert resp["ok"] is True
        assert resp["errors"] is None
        assert resp["result"]["email"] == "newstaff@ercs.org"
        assert resp["result"]["fullName"] == "New Staff"
        assert resp["result"]["role"] == User.Role.STAFF.name
        assert resp["result"]["isActive"] is True
        assert User.objects.filter(email="newstaff@ercs.org").exists()

    def test_hq_admin_role_cannot_be_assigned_with_region(self):
        region = AdminAreaFactory.create(level=AdminAreaLevel.REGION)
        self.force_login(self.hq_admin)
        content = self.query_check(
            self.Mutation.CREATE_USER,
            variables={
                "data": {
                    "email": "regionalhq@ercs.org",
                    "fullName": "Regional HQ",
                    "password": "securepassword123",
                    "role": User.Role.HQ_ADMIN.name,
                    "region": self.gID(region.pk),
                },
            },
        )
        resp = content["data"]["createUser"]
        assert resp["ok"] is False
        assert resp["errors"] is not None
        assert not User.objects.filter(email="regionalhq@ercs.org").exists()

    def test_staff_cannot_create_user(self):
        self.force_login(self.staff)
        content = self.query_check(
            self.Mutation.CREATE_USER,
            variables={
                "data": {
                    "email": "blocked@ercs.org",
                    "fullName": "Blocked",
                    "password": "password123",
                    "role": User.Role.VIEWER.name,
                },
            },
        )
        self.assert_permission_denied(content, "createUser")

    def test_unauthenticated_cannot_create_user(self):
        self.logout()
        content = self.query_check(
            self.Mutation.CREATE_USER,
            variables={
                "data": {
                    "email": "anon@ercs.org",
                    "fullName": "Anon",
                    "password": "password123",
                    "role": User.Role.VIEWER.name,
                },
            },
        )
        self.assert_permission_denied(content, "createUser")

    # ------------------------------------------------------------------
    # updateUser
    # ------------------------------------------------------------------

    def test_hq_admin_can_update_user(self):
        self.force_login(self.hq_admin)
        target = UserFactory.create(role=User.Role.VIEWER, is_active=True)
        content = self.query_check(
            self.Mutation.UPDATE_USER,
            variables={
                "id": self.gID(target.pk),
                "data": {"fullName": "Updated Name", "isActive": False},
            },
        )
        resp = content["data"]["updateUser"]
        assert resp["ok"] is True
        assert resp["result"]["fullName"] == "Updated Name"
        assert resp["result"]["isActive"] is False

    def test_staff_cannot_update_user(self):
        self.force_login(self.staff)
        target = UserFactory.create(role=User.Role.VIEWER)
        content = self.query_check(
            self.Mutation.UPDATE_USER,
            variables={"id": self.gID(target.pk), "data": {"fullName": "Hacked"}},
        )
        self.assert_permission_denied(content, "updateUser")

    # ------------------------------------------------------------------
    # deleteUser
    # ------------------------------------------------------------------

    def test_hq_admin_can_delete_user(self):
        self.force_login(self.hq_admin)
        target = UserFactory.create()
        content = self.query_check(
            self.Mutation.DELETE_USER,
            variables={"id": self.gID(target.pk)},
        )
        resp = content["data"]["deleteUser"]
        assert resp["ok"] is True

        target.refresh_from_db()
        assert target.is_active is False

    def test_hq_admin_cannot_delete_self(self):
        self.force_login(self.hq_admin)
        content = self.query_check(
            self.Mutation.DELETE_USER,
            variables={"id": self.gID(self.hq_admin.pk)},
        )
        resp = content["data"]["deleteUser"]
        assert resp["ok"] is False
        assert resp["errors"] is not None

        self.hq_admin.refresh_from_db()
        assert self.hq_admin.is_active is True

    def test_staff_cannot_delete_user(self):
        self.force_login(self.staff)
        target = UserFactory.create()
        content = self.query_check(
            self.Mutation.DELETE_USER,
            variables={"id": self.gID(target.pk)},
        )
        self.assert_permission_denied(content, "deleteUser")

    # ------------------------------------------------------------------
    # resetUserPassword
    # ------------------------------------------------------------------

    def test_hq_admin_can_reset_password(self):
        self.force_login(self.hq_admin)
        target = UserFactory.create(password="oldpassword")
        content = self.query_check(
            self.Mutation.RESET_USER_PASSWORD,
            variables={"id": self.gID(target.pk), "newPassword": "brandnewpassword"},
        )
        resp = content["data"]["resetUserPassword"]
        assert resp["ok"] is True
        target.refresh_from_db()
        assert target.check_password("brandnewpassword")

    def test_staff_cannot_reset_password(self):
        self.force_login(self.staff)
        target = UserFactory.create(password="oldpassword")
        content = self.query_check(
            self.Mutation.RESET_USER_PASSWORD,
            variables={"id": self.gID(target.pk), "newPassword": "newpassword"},
        )
        self.assert_permission_denied(content, "resetUserPassword")

    # ------------------------------------------------------------------
    # updateMyPassword
    # ------------------------------------------------------------------

    def test_user_can_update_own_password(self):
        user = UserFactory.create(password="currentpassword")
        self.force_login(user)
        content = self.query_check(
            self.Mutation.UPDATE_MY_PASSWORD,
            variables={
                "data": {
                    "currentPassword": "currentpassword",
                    "newPassword": "updatedpassword",
                },
            },
        )
        resp = content["data"]["updateMyPassword"]
        assert resp["ok"] is True
        assert resp["errors"] is None
        user.refresh_from_db()
        assert user.check_password("updatedpassword")

    def test_wrong_current_password_is_rejected(self):
        user = UserFactory.create(password="realpassword")
        self.force_login(user)
        content = self.query_check(
            self.Mutation.UPDATE_MY_PASSWORD,
            variables={
                "data": {
                    "currentPassword": "wrongpassword",
                    "newPassword": "newpassword",
                },
            },
        )
        resp = content["data"]["updateMyPassword"]
        assert resp["ok"] is False
        assert resp["errors"] is not None
        user.refresh_from_db()
        assert user.check_password("realpassword")

    def test_unauthenticated_cannot_update_password(self):
        self.logout()
        content = self.query_check(
            self.Mutation.UPDATE_MY_PASSWORD,
            variables={
                "data": {
                    "currentPassword": "any",
                    "newPassword": "any",
                },
            },
        )
        self.assert_permission_denied(content, "updateMyPassword")

    def test_deleting_missing_user_is_reported_on_the_payload(self):
        self.force_login(self.hq_admin)
        target = UserFactory.create()
        target_id = self.gID(target.pk)
        target.delete()
        content = self.query_check(
            self.Mutation.DELETE_USER,
            variables={"id": target_id},
        )
        resp = content["data"]["deleteUser"]
        assert resp["ok"] is False, resp
        assert resp["errors"][0]["messages"] == "This User no longer exists. It may already have been deleted."
