import pytest
from django.contrib.auth import authenticate
from django.db import IntegrityError, transaction

from apps.accounts.models import User

pytestmark = pytest.mark.django_db


def test_create_user_normalizes_email_and_hashes_password():
    user = User.objects.create_user(
        "  Jane.Doe@Example.COM ", "correct-horse-battery", full_name="Jane"
    )

    assert user.email == "jane.doe@example.com"
    assert user.password != "correct-horse-battery"
    assert user.check_password("correct-horse-battery")
    assert not user.is_staff
    assert not user.is_superuser


def test_user_without_password_cannot_log_in():
    user = User.objects.create_user("invited@example.com", None, full_name="Invited")

    assert not user.has_usable_password()


def test_create_user_requires_email():
    with pytest.raises(ValueError, match="email"):
        User.objects.create_user("", "x", full_name="Nobody")


def test_create_superuser_sets_flags():
    user = User.objects.create_superuser("root@example.com", "a-long-password", full_name="Root")

    assert user.is_staff
    assert user.is_superuser


def test_create_superuser_rejects_contradictory_flags():
    with pytest.raises(ValueError, match="superuser"):
        User.objects.create_superuser("root@example.com", "pw", full_name="Root", is_staff=False)


def test_email_is_unique_case_insensitively():
    User.objects.create_user("dup@example.com", "pw", full_name="A")

    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user("DUP@example.com", "pw", full_name="B")


def test_database_rejects_mixed_case_email_written_around_the_manager():
    user = User.objects.create_user("lower@example.com", "pw", full_name="A")

    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.filter(pk=user.pk).update(email="Lower@Example.com")


def test_authenticate_is_case_insensitive_on_email():
    User.objects.create_user("cashier@example.com", "a-long-password", full_name="C")

    assert authenticate(username="Cashier@Example.com", password="a-long-password") is not None
    assert authenticate(username="cashier@example.com", password="wrong") is None


def test_primary_key_is_uuid7():
    user = User.objects.create_user("pk@example.com", "pw", full_name="P")

    assert user.pk.version == 7


def test_admin_user_pages_render_for_superuser(client):
    admin_user = User.objects.create_superuser(
        "admin@example.com", "a-long-password", full_name="A"
    )
    client.force_login(admin_user)

    assert client.get("/admin/accounts/user/add/").status_code == 200
    assert client.get(f"/admin/accounts/user/{admin_user.pk}/change/").status_code == 200


def test_clean_normalizes_email_entered_in_forms():
    user = User(email=" Mixed@Example.COM ", full_name="M")

    user.clean()

    assert user.email == "mixed@example.com"
