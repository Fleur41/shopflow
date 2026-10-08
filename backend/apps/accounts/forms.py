from django.contrib.auth.forms import AdminUserCreationForm
from django.contrib.auth.forms import UserChangeForm as DjangoUserChangeForm

from .models import User


class UserCreationForm(AdminUserCreationForm):
    class Meta(AdminUserCreationForm.Meta):  # type: ignore[name-defined,misc]
        model = User
        fields = ("email", "full_name")


class UserChangeForm(DjangoUserChangeForm):  # type: ignore[type-arg]
    class Meta(DjangoUserChangeForm.Meta):  # type: ignore[name-defined,misc]
        model = User
        fields = ("email", "full_name", "phone", "is_active", "is_staff", "is_superuser")
