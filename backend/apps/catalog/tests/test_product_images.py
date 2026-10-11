"""Product image uploads (docs/SECURITY.md §7)."""

import io

import pytest
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.audit.models import AuditLog
from apps.catalog.models import Product, TaxRate, UnitOfMeasure

pytestmark = pytest.mark.django_db

GPS_IFD = 0x8825
ORIENTATION = 0x0112


def _image_file(fmt="JPEG", size=(1600, 1200), mode="RGB", name=None, exif=None):
    buffer = io.BytesIO()
    image = Image.new(mode, size, (200, 30, 30, 128) if mode == "RGBA" else (200, 30, 30))
    kwargs = {"exif": exif} if exif is not None else {}
    image.save(buffer, format=fmt, **kwargs)
    return SimpleUploadedFile(name or f"photo.{fmt.lower()}", buffer.getvalue())


def _stored(url):
    """Open a stored rendition from its public URL."""
    key = url.removeprefix("https://media.test/")
    with default_storage.open(key) as f:
        image = Image.open(io.BytesIO(f.read()))
        image.load()
    return image


@pytest.fixture
def milk(biz):
    org = biz.organization
    return Product.objects.create(
        organization=org,
        sku="MILK",
        name="Milk",
        unit=UnitOfMeasure.objects.for_org(org).get(code="PCS"),
        tax_rate=TaxRate.objects.for_org(org).get(name="VAT 16%"),
        selling_price="60.00",
    )


def _upload(client, product, file):
    return client.post(f"/api/v1/products/{product.pk}/image/", {"image": file}, format="multipart")


def test_an_uploaded_photo_is_re_encoded_without_its_metadata(owner_client, milk):
    exif = Image.Exif()
    exif[GPS_IFD] = {1: "S", 2: (1.0, 17.0, 0.0)}  # where the photo was taken
    exif[0x010F] = "PhoneMaker"

    photo = _image_file(exif=exif.tobytes())
    assert Image.open(photo).getexif().get_ifd(GPS_IFD)  # the upload does carry a position
    photo.seek(0)

    response = _upload(owner_client, milk, photo)

    assert response.status_code == 200, response.json()
    body = response.json()
    full, thumb = _stored(body["image_url"]), _stored(body["thumbnail_url"])
    assert (full.format, full.size) == ("WEBP", (1024, 768))
    assert (thumb.format, thumb.size) == ("WEBP", (256, 192))
    assert not full.getexif()
    assert "exif" not in full.info
    assert body["image_url"].startswith("https://media.test/products/")
    assert "photo" not in body["image_url"]  # never the uploaded file name
    assert body["version"] == 2
    assert AuditLog.objects.filter(action="product.image_changed", entity_id=str(milk.pk)).exists()


def test_phone_photos_are_turned_upright(owner_client, milk):
    exif = Image.Exif()
    exif[ORIENTATION] = 6  # taken in portrait: rotate 90°

    response = _upload(owner_client, milk, _image_file(size=(400, 300), exif=exif.tobytes()))

    assert _stored(response.json()["image_url"]).size == (300, 400)


@pytest.mark.parametrize(("fmt", "mode"), [("PNG", "RGBA"), ("WEBP", "RGB")])
def test_png_and_webp_are_accepted_and_transparency_kept(owner_client, milk, fmt, mode):
    response = _upload(owner_client, milk, _image_file(fmt=fmt, mode=mode, size=(300, 300)))

    assert response.status_code == 200
    assert _stored(response.json()["image_url"]).mode == ("RGBA" if mode == "RGBA" else "RGB")


@pytest.mark.parametrize(
    "upload",
    [
        pytest.param(lambda: _image_file(fmt="GIF", mode="P"), id="gif"),
        pytest.param(
            lambda: SimpleUploadedFile("photo.jpg", b"<script>alert(1)</script>"),
            id="script-named-jpg",
        ),
        pytest.param(
            lambda: SimpleUploadedFile("photo.jpg", _image_file().read()[:600]), id="truncated"
        ),
        pytest.param(lambda: _image_file(fmt="PNG", size=(4097, 1)), id="too-many-pixels"),
        pytest.param(
            lambda: SimpleUploadedFile("big.jpg", b"\xff" * (5 * 1024 * 1024 + 1)), id="over-5mb"
        ),
    ],
)
def test_anything_but_a_readable_image_within_limits_is_refused(owner_client, milk, upload):
    response = _upload(owner_client, milk, upload())

    assert response.status_code == 400
    assert response.json()["errors"][0]["pointer"] == "/image"
    milk.refresh_from_db()
    assert (milk.image_key, milk.version) == ("", 1)


def test_a_missing_file_is_a_field_error(owner_client, milk):
    response = owner_client.post(f"/api/v1/products/{milk.pk}/image/", {}, format="multipart")

    assert response.status_code == 400
    assert response.json()["errors"][0]["pointer"] == "/image"


def test_replacing_or_removing_an_image_deletes_the_old_files(
    owner_client, milk, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        first = _upload(owner_client, milk, _image_file()).json()
    old_keys = [
        url.removeprefix("https://media.test/")
        for url in (first["image_url"], first["thumbnail_url"])
    ]

    with django_capture_on_commit_callbacks(execute=True):
        second = _upload(owner_client, milk, _image_file(fmt="PNG")).json()
    assert not any(default_storage.exists(key) for key in old_keys)

    with django_capture_on_commit_callbacks(execute=True):
        removed = owner_client.delete(f"/api/v1/products/{milk.pk}/image/").json()
    assert (removed["image_url"], removed["thumbnail_url"]) == (None, None)
    assert not default_storage.exists(second["image_url"].removeprefix("https://media.test/"))


def test_only_people_who_manage_products_can_change_images(cashier_client, milk):
    assert _upload(cashier_client, milk, _image_file()).status_code == 403
    assert cashier_client.delete(f"/api/v1/products/{milk.pk}/image/").status_code == 403
