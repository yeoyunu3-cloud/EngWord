import os


def test_security_headers_on_index(client):
    r = client.get("/")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    csp = r.headers["content-security-policy"]
    for part in ["default-src 'self'", "connect-src 'self'", "frame-ancestors 'none'",
                 "font-src https://fonts.gstatic.com", "img-src 'self' data: blob:"]:
        assert part in csp


def test_security_headers_on_api(client):
    assert "content-security-policy" in client.get("/api/books").headers


def test_load_dotenv_does_not_override(server_mod, tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("# comment\nA_X=1\nA_Y=2\n")
    monkeypatch.setenv("A_X", "keep")
    monkeypatch.delenv("A_Y", raising=False)
    server_mod.load_dotenv(f)
    assert os.environ["A_X"] == "keep"
    assert os.environ["A_Y"] == "2"


def test_index_is_revalidated(client):
    # 배포 직후 옛 화면이 캐시에서 뜨지 않게, 화면은 매번 서버에 확인한다
    assert client.get("/").headers["cache-control"] == "no-cache"
