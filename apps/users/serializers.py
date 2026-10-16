import typing

from rest_framework import serializers

from .models import User, UserRole


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = User
        fields = ["email", "full_name", "role", "region", "is_active", "password"]

    @typing.override
    def validate(self, attrs: dict[str, typing.Any]) -> dict[str, typing.Any]:
        role = attrs.get("role", self.instance.role if self.instance else UserRole.VIEWER)
        region = attrs.get("region", self.instance.region if self.instance else None)
        # HQ Admin is an organisation-wide role; it cannot be assigned to region-scoped users
        if role == UserRole.HQ_ADMIN and region is not None:
            raise serializers.ValidationError({"role": "HQ Admin role cannot be assigned to a regional user."})
        return attrs

    @typing.override
    def create(self, validated_data: dict[str, typing.Any]) -> User:
        password = validated_data.pop("password", None)
        return User.objects.create_user(password=password or "", **validated_data)  # type: ignore[reportAttributeAccessIssue]

    @typing.override
    def update(self, instance: User, validated_data: dict[str, typing.Any]) -> User:
        validated_data.pop("password", None)
        return super().update(instance, validated_data)
