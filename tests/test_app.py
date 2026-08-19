from fastapi.testclient import TestClient

from web.main import app
import web.main as web_main
from bot.views import ApplicationModal, PromotionModal
from shared.config import _build_config_from_env


def test_root_page_loads():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200


def test_public_base_url_replaces_stale_local_oauth_redirect(monkeypatch):
    monkeypatch.setenv("WEB_BASE_URL", "https://londo.example.com")
    monkeypatch.setenv("DISCORD_OAUTH_REDIRECT_URI", "http://localhost:8080/auth/callback")

    config = _build_config_from_env()

    assert config["web"]["oauth"]["redirect_uri"] == "https://londo.example.com/auth/callback"


def test_host_port_overrides_local_web_port(monkeypatch):
    monkeypatch.setenv("WEB_PORT", "8080")
    monkeypatch.setenv("PORT", "18432")

    config = _build_config_from_env()

    assert config["web"]["port"] == 18432


def test_oauth_token_failure_exposes_safe_error_code(monkeypatch):
    class FailedTokenResponse:
        status_code = 400
        content = b'{"error":"invalid_client","error_description":"bad secret"}'

        def json(self):
            return {"error": "invalid_client", "error_description": "bad secret"}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return FailedTokenResponse()

    monkeypatch.setattr(web_main.httpx, "AsyncClient", lambda: FakeClient())
    monkeypatch.setattr(web_main, "config", {
        "web": {
            "oauth": {
                "client_id": "client",
                "client_secret": "secret",
                "redirect_uri": "https://londo.bothost.tech/auth/callback",
            }
        }
    })
    monkeypatch.setattr(web_main, "log_bot_error", lambda *args, **kwargs: None)

    response = TestClient(app).get("/auth/callback?code=test-code")

    assert response.status_code == 400
    assert "invalid_client" in response.json()["detail"]


async def fake_current_user(request):
    return {"id": "123", "username": "member", "roles": []}


def test_approved_user_without_site_roles_is_sent_to_access_denied(monkeypatch):
    monkeypatch.setattr(web_main, "get_current_user", fake_current_user)
    monkeypatch.setattr(web_main, "_profile_is_approved", lambda current_user: True)

    response = TestClient(app).get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/access/denied"


def test_recruiter_roles_are_limited_to_their_server():
    memphis_recruiter = {"roles": [1539527961055596625]}
    phoenix_recruiter = {"roles": [1538952822568263701, 1538953091532066977]}

    assert web_main._has_server_access(memphis_recruiter, "memphis")
    assert not web_main._has_server_access(memphis_recruiter, "phoenix")
    assert web_main._has_server_access(phoenix_recruiter, "phoenix")
    assert not web_main._has_server_access(phoenix_recruiter, "memphis")


def test_regular_recruiter_cannot_view_logs():
    assert not web_main._has_logs_access({"roles": [1538952822568263701]})
    assert web_main._has_logs_access({"roles": [1538952888640868390]})
    assert not web_main._has_bot_errors_access({"roles": [1538952888640868390]})
    assert web_main._has_bot_errors_access({"roles": [1538988980446437396]})


def test_curators_and_depowners_are_limited_to_their_server():
    memphis_roles = [1539544554980769812, 1539518708471300176]
    phoenix_roles = [1538952888640868390, 1539545567615651850]

    for role_id in memphis_roles:
        user = {"roles": [role_id]}
        assert web_main._has_server_access(user, "memphis")
        assert not web_main._has_server_access(user, "phoenix")
    for role_id in phoenix_roles:
        user = {"roles": [role_id]}
        assert web_main._has_server_access(user, "phoenix")
        assert not web_main._has_server_access(user, "memphis")


def test_owner_and_chief_moderator_have_global_server_access():
    for role_id in (1538988980446437396, 1539535176881930303):
        user = {"roles": [role_id]}
        assert web_main._has_server_access(user, "memphis")
        assert web_main._has_server_access(user, "phoenix")
        assert web_main._has_bot_errors_access(user)


def test_phoenix_recruiter_workspace_only_shows_phoenix(monkeypatch):
    async def current_user(request):
        return {"id": "123", "username": "phoenix", "roles": [1538952822568263701]}

    monkeypatch.setattr(web_main, "get_current_user", current_user)
    monkeypatch.setattr(web_main, "_profile_is_approved", lambda user: True)

    response = TestClient(app).get("/server/phoenix")

    assert response.status_code == 200
    assert "Phoenix" in response.text
    assert "Memphis" not in response.text
    assert "Логи" not in response.text


def test_server_workspace_links_logs_to_current_server(monkeypatch):
    async def current_user(request):
        return {"id": "123", "username": "owner", "roles": [1538988980446437396]}

    monkeypatch.setattr(web_main, "get_current_user", current_user)
    monkeypatch.setattr(web_main, "_profile_is_approved", lambda user: True)

    response = TestClient(app).get("/server/memphis")

    assert response.status_code == 200
    assert '/logs?server=memphis&category=applications' in response.text


def test_single_server_promotions_does_not_show_redundant_server_tab(monkeypatch):
    async def current_user(request):
        return {"id": "123", "username": "memphis", "roles": [1539527961055596625]}

    monkeypatch.setattr(web_main, "get_current_user", current_user)
    monkeypatch.setattr(web_main, "_profile_is_approved", lambda user: True)

    response = TestClient(app).get("/promotions?server=memphis")

    assert response.status_code == 200
    assert '/promotions?server=memphis&status=' not in response.text


def test_cabinet_title_names_the_family_applications_and_server(monkeypatch):
    async def current_user(request):
        return {"id": "123", "username": "memphis", "roles": [1539527961055596625]}

    monkeypatch.setattr(web_main, "get_current_user", current_user)
    monkeypatch.setattr(web_main, "_profile_is_approved", lambda user: True)

    response = TestClient(app).get("/cabinet/memphis")

    assert response.status_code == 200
    assert "Заявки в семью — Memphis" in response.text
    assert "Кабинет Memphis" not in response.text


def test_app_modal_has_url_field_for_screenshot():
    modal = ApplicationModal("memphis")
    assert any(getattr(item, "label", None) == "Ссылка на скриншот персонажа" for item in modal.children)


def test_app_modal_has_separate_static_field():
    modal = ApplicationModal("memphis")
    labels = [getattr(item, "label", None) for item in modal.children]
    assert "Игровое имя и фамилия" in labels
    assert "Static ID" in labels


def test_promotion_modal_has_character_name_field():
    modal = PromotionModal("young_londo")
    labels = [getattr(item, "label", None) for item in modal.children]
    assert "Игровой никнейм на сервере" in labels
