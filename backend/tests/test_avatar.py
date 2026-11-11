"""Avatars: upload -> 256 px WebP, provider photo import, public route."""

import asyncio
import io
import uuid
import zlib

import httpx
import pytest
from PIL import Image

from app.core.auth import create_access_token
from app.core.config import settings
from app.db import users_db
from app.services import avatar as av


@pytest.fixture(autouse=True)
def _fast_users(monkeypatch, client):
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")


def _user():
    u = users_db.create_user(f"av-{uuid.uuid4().hex[:8]}", "pw-123456789")
    token = create_access_token({"sub": u["username"]})
    return u, {"Authorization": f"Bearer {token}"}


def _img(fmt, size=(1000, 600), mode="RGB", color=(200, 30, 30), **kw):
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, fmt, **kw)
    return buf.getvalue()


def _put(client, headers, data, ctype="image/jpeg"):
    return client.put(
        "/api/account/avatar", headers=headers, files={"file": ("a", data, ctype)}
    )


def test_jpeg_becomes_256_webp_without_exif():
    exif = Image.Exif()
    exif[0x010F] = "SecretCam"
    out = av.process_upload(_img("JPEG", exif=exif.tobytes()), "image/jpeg")
    im = Image.open(io.BytesIO(out))
    assert im.format == "WEBP" and im.size == (256, 256)
    assert not im.info.get("exif")


def test_png_alpha_keeps_transparency():
    out = av.process_upload(
        _img("PNG", (300, 300), "RGBA", (255, 0, 0, 0)), "image/png"
    )
    im = Image.open(io.BytesIO(out)).convert("RGBA")
    assert im.getpixel((10, 10))[3] == 0


def test_wrong_type_is_415():
    with pytest.raises(av.ApiError) as e:
        av.process_upload(b"just some text", "image/png")
    assert (e.value.status, e.value.code) == (415, "avatar_type")
    with pytest.raises(av.ApiError) as e:
        av.process_upload(_img("BMP"), "image/png")
    assert e.value.status == 415


def test_oversize_is_413_in_service():
    with pytest.raises(av.ApiError) as e:
        av.process_upload(b"x" * (2 * 1024 * 1024 + 1), "image/png")
    assert (e.value.status, e.value.code) == (413, "avatar_too_large")


def _png_header(w, h):
    def chunk(t, d):
        c = t + d
        return len(d).to_bytes(4, "big") + c + zlib.crc32(c).to_bytes(4, "big")

    ihdr = w.to_bytes(4, "big") + h.to_bytes(4, "big") + bytes([8, 2, 0, 0, 0])
    idat = zlib.compress(b"\x00" * 30)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )


def test_decompression_bomb_is_422():
    with pytest.raises(av.ApiError) as e:
        av.process_upload(_png_header(10000, 10000), "image/png")
    assert (e.value.status, e.value.code) == (422, "avatar_unreadable")


def _big_png(w, h):
    """A real, fully decodable RGBA PNG of w×h that compresses to a few KB."""
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), (0, 0, 0, 0)).save(buf, "PNG", optimize=False)
    return buf.getvalue()


def test_large_dimension_small_png_is_422_before_decode(monkeypatch):
    """I-3: a 4500×4500 PNG (20 MP, a few KB) is refused from its header,
    before Pillow allocates the full-size bitmap."""
    from PIL import ImageFile

    data = _big_png(4500, 4500)
    assert len(data) < 200_000
    loads = []
    real_load = ImageFile.ImageFile.load
    monkeypatch.setattr(
        ImageFile.ImageFile,
        "load",
        lambda self: loads.append(self.size) or real_load(self),
    )
    with pytest.raises(av.ApiError) as e:
        av.process_upload(data, "image/png")
    assert (e.value.status, e.value.code) == (422, "avatar_unreadable")
    assert loads == []
    assert av.MAX_PIXELS <= 16_000_000


def test_route_large_dimension_png_is_422(client):
    _, h = _user()
    r = _put(client, h, _big_png(5000, 4000), "image/png")
    assert r.status_code == 422 and r.json()["error_code"] == "avatar_unreadable"


def test_large_jpeg_is_drafted_down_and_accepted(monkeypatch):
    """A 24 MP camera photo is fine: JPEG decodes at 1/8 scale (draft), so
    the pixel cap applies to what is actually decoded."""
    data = _img("JPEG", (6000, 4000), quality=30)
    assert len(data) < av.MAX_BYTES
    sizes = []
    real_load = Image.Image.load

    def spy(self):
        sizes.append(self.size)
        return real_load(self)

    monkeypatch.setattr(Image.Image, "load", spy)
    out = av.process_upload(data, "image/jpeg")
    assert Image.open(io.BytesIO(out)).size == (256, 256)
    assert sizes and max(w * h for w, h in sizes) <= 1500 * 1000  # not 24 MP


def test_exif_orientation_still_applied():
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° clockwise to display
    img = Image.new("RGB", (1200, 600), (0, 0, 255))
    img.paste((255, 0, 0), (0, 0, 600, 600))  # left half red
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif.tobytes())
    out = Image.open(io.BytesIO(av.process_upload(buf.getvalue(), "image/jpeg")))
    # displayed upright the image is 600×1200 with red on top: the centre
    # square straddles it, so the top row is red and the bottom row blue
    r, g, b = out.convert("RGB").getpixel((128, 5))
    assert r > 200 and b < 60
    r, g, b = out.convert("RGB").getpixel((128, 250))
    assert b > 200 and r < 60


def test_one_decode_at_a_time(monkeypatch):
    """Decodes are serialised by a module-level lock (held in the worker
    thread, so the event loop never waits on it)."""
    seen = []
    real_open = Image.open

    def spy(*a, **k):
        seen.append(av._DECODE_SLOT.acquire(blocking=False))
        return real_open(*a, **k)

    monkeypatch.setattr(av.Image, "open", spy)
    av.process_upload(_img("PNG", (300, 300)), "image/png")
    assert seen == [False]  # already held by this decode
    assert av._DECODE_SLOT.acquire(blocking=False)  # released afterwards
    av._DECODE_SLOT.release()


def test_truncated_image_is_422():
    with pytest.raises(av.ApiError) as e:
        av.process_upload(_img("PNG")[:200], "image/png")
    assert e.value.status == 422


def test_route_upload_serve_delete(client):
    u, h = _user()
    r = _put(client, h, _img("JPEG"))
    assert r.status_code == 200, r.text
    url = r.json()["avatar_url"]
    assert f"/api/avatars/{u['id']}.webp?v=" in url
    g = client.get(f"/api/avatars/{u['id']}.webp")
    assert g.status_code == 200
    assert g.headers["content-type"] == "image/webp"
    assert g.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert Image.open(io.BytesIO(g.content)).size == (256, 256)
    me = users_db.get_user_by_id(u["id"])
    assert me["avatar_source"] == "upload"
    d = client.delete("/api/account/avatar", headers=h)
    assert d.status_code == 200 and d.json() == {"avatar_url": None}
    assert client.get(f"/api/avatars/{u['id']}.webp").status_code == 404
    assert users_db.get_user_by_id(u["id"])["avatar_source"] is None


def test_route_requires_auth_and_codes(client):
    assert client.put("/api/account/avatar").status_code in (401, 403)
    _, h = _user()
    r = _put(client, h, b"hello", "text/plain")
    assert (r.status_code, r.json()["error_code"]) == (415, "avatar_type")
    r = _put(client, h, b"x" * (2 * 1024 * 1024 + 10), "image/png")
    assert (r.status_code, r.json()["error_code"]) == (413, "avatar_too_large")
    # just over 2 MB but under the middleware's slack: the route's own check
    r = _put(client, h, b"x" * (2 * 1024 * 1024 + 1), "image/png")
    assert (r.status_code, r.json()["error_code"]) == (413, "avatar_too_large")
    r = _put(client, h, _img("PNG")[:200], "image/png")
    assert (r.status_code, r.json()["error_code"]) == (422, "avatar_unreadable")
    r = client.put("/api/account/avatar", headers=h)
    assert r.status_code == 422


def test_get_non_uuid_is_404(client):
    assert client.get("/api/avatars/not-a-uuid.webp").status_code == 404
    assert client.get("/api/avatars/..%2f..%2fetc.webp").status_code == 404
    assert client.get(f"/api/avatars/{uuid.uuid4()}.webp").status_code == 404


def test_user_payload_shows_avatar(client):
    from app.core.session_payload import user_payload

    u, h = _user()
    assert user_payload(users_db.get_user_by_id(u["id"]))["avatar_url"] is None
    _put(client, h, _img("PNG"), "image/png")
    assert user_payload(users_db.get_user_by_id(u["id"]))["avatar_url"]


def test_save_avatar_is_atomic_no_temp_left(client):
    u, _ = _user()
    av.save_avatar(u["id"], av.process_upload(_img("PNG"), "image/png"), "upload")
    names = [p.name for p in av.avatar_path(u["id"]).parent.iterdir()]
    assert f"{u['id']}.webp" in names
    assert not [n for n in names if n.startswith(u["id"]) and n.endswith(".tmp")]


def run(coro):
    return asyncio.run(coro)


def test_import_refuses_unlisted_host_and_http(client):
    u, _ = _user()
    assert run(av.import_provider_photo(u["id"], "https://evil.example/x.png")) is False
    assert (
        run(av.import_provider_photo(u["id"], "http://lh3.googleusercontent.com/x.png"))
        is False
    )
    assert not av.avatar_path(u["id"]).exists()


_REAL_CLIENT = httpx.AsyncClient


def _patch_transport(monkeypatch, handler):
    real = _REAL_CLIENT

    def factory(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return real(*a, **kw)

    monkeypatch.setattr(av.httpx, "AsyncClient", factory)


def test_import_success(client, monkeypatch):
    u, _ = _user()
    data = _img("JPEG")
    _patch_transport(
        monkeypatch,
        lambda req: httpx.Response(
            200, content=data, headers={"content-type": "image/jpeg"}
        ),
    )
    assert (
        run(av.import_provider_photo(u["id"], "https://lh3.googleusercontent.com/a"))
        is True
    )
    assert av.avatar_path(u["id"]).exists()
    assert users_db.get_user_by_id(u["id"])["avatar_source"] == "provider"


def test_import_redirect_rules(client, monkeypatch):
    u, _ = _user()
    data = _img("PNG")

    def handler(req):
        if req.url.host == "lh3.googleusercontent.com":
            return httpx.Response(302, headers={"location": "https://evil.example/x"})
        return httpx.Response(200, content=data, headers={"content-type": "image/png"})

    _patch_transport(monkeypatch, handler)
    assert (
        run(av.import_provider_photo(u["id"], "https://lh3.googleusercontent.com/a"))
        is False
    )

    def handler2(req):
        if req.url.host == "lh3.googleusercontent.com":
            return httpx.Response(
                302, headers={"location": "https://avatars.githubusercontent.com/z"}
            )
        return httpx.Response(200, content=data, headers={"content-type": "image/png"})

    _patch_transport(monkeypatch, handler2)
    assert (
        run(av.import_provider_photo(u["id"], "https://lh3.googleusercontent.com/a"))
        is True
    )


def test_import_caps_size_and_survives_errors(client, monkeypatch):
    u, _ = _user()
    _patch_transport(
        monkeypatch,
        lambda req: httpx.Response(
            200,
            content=b"x" * (2 * 1024 * 1024 + 5),
            headers={"content-type": "image/png"},
        ),
    )
    assert (
        run(
            av.import_provider_photo(u["id"], "https://avatars.githubusercontent.com/a")
        )
        is False
    )

    def boom(req):
        raise httpx.ConnectError("down")

    _patch_transport(monkeypatch, boom)
    assert (
        run(
            av.import_provider_photo(u["id"], "https://avatars.githubusercontent.com/a")
        )
        is False
    )
    assert not av.avatar_path(u["id"]).exists()


def test_data_dir_used():
    assert str(av.avatar_path("abc")).startswith(settings.data_dir)
