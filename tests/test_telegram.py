import io
import json
import logging
import sys

import httpx
import pytest

from vigil.telegram import CAPTION_MAX, Telegram, TelegramError, main

TOKEN = "123456:SECRET-token"


def bot(handler, chat="@volcano_vigil"):
    return Telegram(httpx.Client(transport=httpx.MockTransport(handler)), TOKEN, chat)


def ok(result):
    return httpx.Response(200, json={"ok": True, "result": result})


def test_a_photo_is_posted_as_multipart_with_the_chat_and_the_caption():
    seen = []

    def handler(request):
        seen.append(request)
        return ok({"message_id": 42})

    message_id = bot(handler).send_photo(b"\xff\xd8jpeg", "Lava fountaining seen")

    assert message_id == 42
    request = seen[0]
    assert request.url.path == f"/bot{TOKEN}/sendPhoto"
    body = request.content
    assert b'name="chat_id"' in body and b"@volcano_vigil" in body
    assert b'name="caption"' in body and b"Lava fountaining seen" in body
    assert b'name="photo"; filename="alert.jpg"' in body and b"\xff\xd8jpeg" in body


def test_a_caption_over_telegrams_limit_is_refused_before_any_request():
    def handler(request):
        raise AssertionError("no request expected")

    with pytest.raises(ValueError, match="1024"):
        bot(handler).send_photo(b"jpeg", "x" * (CAPTION_MAX + 1))


def test_an_api_error_says_what_failed_without_the_token():
    def handler(request):
        return httpx.Response(401, json={"ok": False, "error_code": 401, "description": "Unauthorized"})

    with pytest.raises(TelegramError) as raised:
        bot(handler).send_message("hello")

    assert "sendMessage: 401 Unauthorized" in str(raised.value)
    assert TOKEN not in str(raised.value) and raised.value.__cause__ is None


def test_a_network_error_never_carries_the_token():
    def handler(request):
        raise httpx.ConnectError(f"cannot reach {request.url}")

    with pytest.raises(TelegramError) as raised:
        bot(handler).send_message("hello")

    assert TOKEN not in str(raised.value) and "<token>" in str(raised.value)
    assert raised.value.__cause__ is None and raised.value.__suppress_context__  # `from None`: no URL in a traceback


def test_check_says_who_posts_where_and_whether_it_may():
    answers = {"getMe": {"id": 7, "username": "volcano_vigil_bot"},
               "getChat": {"id": -1001, "title": "Volcano Vigil", "type": "channel"},
               "getChatMember": {"status": "administrator", "can_post_messages": True}}

    def handler(request):
        return ok(answers[request.url.path.rsplit("/", 1)[1]])

    assert bot(handler).check() == {"bot": "@volcano_vigil_bot", "chat": "Volcano Vigil", "chat_id": -1001,
                                    "type": "channel", "status": "administrator", "can_post": True}


def test_a_member_that_is_not_an_admin_may_not_post():
    answers = {"getMe": {"id": 7, "username": "b"}, "getChat": {"id": -1, "title": "c", "type": "channel"},
               "getChatMember": {"status": "left"}}

    result = bot(lambda request: ok(answers[request.url.path.rsplit("/", 1)[1]])).check()

    assert result["can_post"] is False


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr("vigil.settings.load_dotenv", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "@volcano_vigil")
    monkeypatch.setenv("SOURCES_PATH", "config/sources.yaml")


def test_cli_check_prints_the_summary_and_never_the_token(env, monkeypatch, capsys):
    monkeypatch.setattr(Telegram, "check", lambda self: {"bot": "@b", "chat": "Volcano Vigil", "chat_id": -1001,
                                                         "type": "channel", "status": "administrator",
                                                         "can_post": True})

    main(["check"])

    out = capsys.readouterr().out
    assert "@b posts to Volcano Vigil (-1001, channel): administrator, may post: yes" in out
    assert TOKEN not in out
    assert logging.getLogger("httpx").level == logging.WARNING  # its request lines would print the token


def test_cli_check_prints_a_channel_name_a_windows_console_cannot_show(env, monkeypatch):
    monkeypatch.setattr(Telegram, "check", lambda self: {"bot": "@b", "chat": "Volcano Vigil · Kīlauea",
                                                         "chat_id": -1001, "type": "channel",
                                                         "status": "administrator", "can_post": True})
    console = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(console, encoding="cp1252"))

    main(["check"])

    sys.stdout.flush()
    assert b"posts to Volcano Vigil \xb7 K?lauea (-1001, channel)" in console.getvalue()


def test_cli_test_posts_a_message_that_says_it_is_not_an_alert(env, monkeypatch, capsys):
    sent = []
    monkeypatch.setattr(Telegram, "send_message", lambda self, text: sent.append(text) or 9)

    main(["test"])

    assert "not an alert" in sent[0] and "No es una alerta" in sent[0]
    assert "https://www.usgs.gov/volcanoes/kilauea" in sent[0]
    assert "message 9" in capsys.readouterr().out


def test_cli_needs_the_token_and_the_channel(monkeypatch, capsys):
    monkeypatch.setattr("vigil.settings.load_dotenv", lambda: None)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    with pytest.raises(SystemExit):
        main(["check"])

    assert "TELEGRAM_BOT_TOKEN" in capsys.readouterr().err
