"""The development-only media view serves uploads as inert content."""

from django.test import RequestFactory, override_settings

from apps.common.views import serve_media


def test_uploads_are_served_inline_unsniffable_and_sandboxed(tmp_path):
    (tmp_path / "products").mkdir()
    (tmp_path / "products" / "a.webp").write_bytes(b"RIFF....WEBP")

    with override_settings(MEDIA_ROOT=str(tmp_path)):
        response = serve_media(RequestFactory().get("/media/products/a.webp"), "products/a.webp")

    assert response.status_code == 200
    assert response["Content-Type"] == "image/webp"
    assert response["Content-Disposition"] == "inline"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Content-Security-Policy"] == "default-src 'none'; sandbox"
    response.close()
