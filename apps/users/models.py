import datetime
import typing
import uuid

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django_choices_field import IntegerChoicesField
from django_stubs_ext.db.models.manager import RelatedManager

from .managers import UserManager


class UserRole(models.IntegerChoices):
    """Access-control roles assigned to users."""

    HQ_ADMIN = 10, "HQ Admin"
    REGIONAL_ADMIN = 20, "Regional Admin"
    STAFF = 30, "Staff"
    PARTNER = 40, "Partner"
    VIEWER = 50, "Viewer"


class User(AbstractBaseUser, PermissionsMixin):
    """Custom user model with email as the login identifier.

    Roles drive access control throughout the app:
    - HQ_ADMIN: full access across all regions (aggregate and regional dashboards, user management)
      Must not be scoped to a region.
    - REGIONAL_ADMIN: access scoped to their assigned region
    - STAFF, PARTNER, VIEWER: read-access tiers
    """

    Role = UserRole  # convenience alias

    id = models.UUIDField[uuid.UUID, uuid.UUID](
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    email = models.EmailField[str, str](unique=True)
    full_name = models.CharField[str, str](max_length=255)
    role: int = IntegerChoicesField(choices_enum=UserRole, default=UserRole.VIEWER)  # type: ignore[reportAssignmentType]
    region = models.ForeignKey(
        "geo.AdminArea",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="regional_admins",
        help_text="Only meaningful for REGIONAL_ADMIN role; must be a REGION-level area.",
    )
    is_active = models.BooleanField[bool, bool](default=True)  # type: ignore[reportAssignmentType]
    is_staff = models.BooleanField[bool, bool](default=False)
    mfa_enabled = models.BooleanField[bool, bool](default=False)
    created_at = models.DateTimeField[datetime.datetime, datetime.datetime](auto_now_add=True)

    # last_login is provided by AbstractBaseUser

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    objects = UserManager()

    # reverse relation type hints
    uploaded_reports: typing.ClassVar[RelatedManager["apps.reports.models.Report"]]  # type: ignore[name-defined]  # noqa: F821
    news_posts: typing.ClassVar[RelatedManager["apps.content.models.NewsPost"]]  # type: ignore[name-defined]  # noqa: F821

    class Meta:  # type: ignore[reportIncompatibleVariableOverride]
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ["full_name"]

    @typing.override
    def __str__(self) -> str:
        return f"{self.full_name} <{self.email}>"
