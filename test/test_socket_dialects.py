"""Socket handlers driven directly: framing, failure templates, TLS and the two authenticating dialects."""
import json
import ssl
import struct

import pytest

from je_action_core import (
    END_MARKER,
    MAX_FRAME_BYTES,
    ActionRequestHandler,
    EnvelopeTokenRequestHandler,
    Framing,
    ReplyMessages,
    SecretHeaderRequestHandler,
    SocketServerSettings,
    secret_matches,
    server_tls_context,
)

END = END_MARKER.encode() + b"\n"
SECRET = "s3cret"  # noqa: S105 - a test value, not a credential
_FRAME = struct.Struct("!I")


class _FakeConnection:
    def __init__(self, request: bytes) -> None:
        self._pending = bytearray(request)
        self.sent = bytearray()
        self.timeout = None

    def recv(self, size: int) -> bytes:
        chunk = bytes(self._pending[:size])
        del self._pending[:size]
        return chunk

    def sendall(self, data: bytes) -> None:
        self.sent.extend(data)

    def settimeout(self, value) -> None:
        self.timeout = value


class _FakeServer:
    def __init__(self, settings: SocketServerSettings) -> None:
        self.settings = settings
        self.stopped = False

    def request_stop(self) -> None:
        self.stopped = True


def _echo_records(document):
    return {f"execute: {action}": action[1]["value"] for action in document}


def _exchange(handler, request: bytes, **settings):
    settings.setdefault("execute", _echo_records)
    server = _FakeServer(SocketServerSettings(**settings))
    connection = _FakeConnection(request)
    handler(connection, ("127.0.0.1", 0), server)
    return bytes(connection.sent), server.stopped


def _echo(value: str) -> bytes:
    return json.dumps([["echo", {"value": value}]]).encode()


def _frame(body: bytes) -> bytes:
    return _FRAME.pack(len(body)) + body


class TestBaseHandler:

    def test_empty_request_is_parsed_and_answered(self):
        reply, _ = _exchange(ActionRequestHandler, b"")
        assert reply == b"Expecting value: line 1 column 1 (char 0)\n" + END

    def test_record_template_and_failure_templates(self):
        messages = ReplyMessages(record="{key} -> {value}", error="execution error: {error!r}",
                                 json_error="json error: {error!r}", refused="forbidden: {error}")

        def refuse(document):
            raise PermissionError("denied")

        def explode(document):
            raise RuntimeError("boom")
        assert _exchange(ActionRequestHandler, _echo("hi"), messages=messages)[0] == \
            b"execute: ['echo', {'value': 'hi'}] -> hi\n" + END
        assert _exchange(ActionRequestHandler, b"[", messages=messages)[0].startswith(b"json error: JSONDecodeError(")
        assert _exchange(ActionRequestHandler, _echo("x"), messages=messages, validate=refuse)[0] == \
            b"forbidden: denied\n" + END
        assert _exchange(ActionRequestHandler, _echo("x"), messages=messages, execute=explode)[0] == \
            b"execution error: RuntimeError('boom')\n" + END

    def test_decode_errors_are_dropped_answered_or_replaced(self):
        assert _exchange(ActionRequestHandler, b"\xff") == (b"", False)
        reply, _ = _exchange(ActionRequestHandler, b"\xff", messages=ReplyMessages(decode_error="decode error"))
        assert reply == b"decode error\n" + END
        reply, _ = _exchange(ActionRequestHandler, b"\xff", decode_errors="replace")
        assert reply.endswith(END)

    def test_quit_reply_is_optional(self):
        assert _exchange(ActionRequestHandler, b"quit_server") == (b"", True)
        messages = ReplyMessages(quit="bye")
        assert _exchange(ActionRequestHandler, b"quit_server", messages=messages) == (b"bye\n", True)

    def test_log_command_template_can_hide_the_text(self):
        logged = []
        _exchange(ActionRequestHandler, _echo("secret-ish"), log_info=logged.append,
                  messages=ReplyMessages(log_command="received {size} bytes"))
        assert logged == [f"received {len(_echo('secret-ish'))} bytes"]

    def test_length_prefixed_frames(self):
        reply, _ = _exchange(ActionRequestHandler, _frame(_echo("hi")), framing=Framing.LENGTH_PREFIX)
        assert reply == _frame(b"hi\n") + _frame(END)
        for header in (_FRAME.pack(0), _FRAME.pack(MAX_FRAME_BYTES + 1), b"\x00\x00"):
            assert _exchange(ActionRequestHandler, header, framing=Framing.LENGTH_PREFIX) == (b"", False)
        assert _exchange(ActionRequestHandler, _FRAME.pack(10) + b"short", framing=Framing.LENGTH_PREFIX) == \
            (b"", False)

    def test_recv_timeout_is_applied(self):
        server = _FakeServer(SocketServerSettings(execute=_echo_records, recv_timeout=3.0))
        connection = _FakeConnection(_echo("t"))
        ActionRequestHandler(connection, ("127.0.0.1", 0), server)
        assert connection.timeout == 3.0

    def test_tls_wraps_the_connection_and_a_failed_handshake_is_dropped(self):
        wrapped = []

        class _Context:
            def wrap_socket(self, sock, server_side):
                wrapped.append(server_side)
                return sock

        class _BrokenContext:
            def wrap_socket(self, sock, server_side):
                raise ssl.SSLError("bad handshake")
        assert _exchange(ActionRequestHandler, _echo("tls"), tls_context=_Context())[0] == b"tls\n" + END
        assert wrapped == [True]
        logged = []
        assert _exchange(ActionRequestHandler, _echo("x"), tls_context=_BrokenContext(), log_error=logged.append) \
            == (b"", False)
        assert logged[0].startswith("TLS handshake failed")


class TestSecretHeaderDialect:

    def test_without_a_secret_it_is_the_base_handler_but_ignores_empty_requests(self):
        assert _exchange(SecretHeaderRequestHandler, _echo("a"))[0] == b"a\n" + END
        assert _exchange(SecretHeaderRequestHandler, b"") == (b"", False)
        assert _exchange(SecretHeaderRequestHandler, b"   ")[0].endswith(END)

    @pytest.mark.parametrize("request_bytes", [_echo("a"), b"AUTH wrong\n[]", b"AUTH " + SECRET.encode(),
                                               b"TOKEN " + SECRET.encode() + b"\n[]"])
    def test_refusals(self, request_bytes):
        messages = ReplyMessages(auth_refused="auth error")
        assert _exchange(SecretHeaderRequestHandler, request_bytes, secret=SECRET, messages=messages) == \
            (b"auth error\n" + END, False)

    def test_the_header_unlocks_the_document_and_quit(self):
        good = b"AUTH " + SECRET.encode() + b"\n"
        assert _exchange(SecretHeaderRequestHandler, good + _echo("ok"), secret=SECRET)[0] == b"ok\n" + END
        assert _exchange(SecretHeaderRequestHandler, good + b"quit_server", secret=SECRET) == (b"", True)

    def test_custom_prefix(self):
        request = SECRET.encode() + b"\n" + _echo("p")
        assert _exchange(SecretHeaderRequestHandler, request, secret=SECRET, auth_prefix="")[0] == b"p\n" + END


class TestEnvelopeTokenDialect:

    MESSAGES = ReplyMessages(record="{value}", error="Error: {error}", quit="Server shutting down",
                             auth_required="Error: token required", auth_refused="Error: unauthorised")

    def _ask(self, request: bytes, secret=None):
        return _exchange(EnvelopeTokenRequestHandler, request, secret=secret, messages=self.MESSAGES,
                         decode_errors="replace")

    def test_bare_documents_and_quit_without_a_secret(self):
        assert self._ask(_echo("hi")) == (b"hi\n" + END, False)
        assert self._ask(b"quit_server") == (b"Server shutting down\n", True)
        assert self._ask(b"") == (b"", False)
        assert self._ask(b"not json") == (b"Error: Expecting value: line 1 column 1 (char 0)\n" + END, False)

    def test_a_secret_needs_the_envelope(self):
        assert self._ask(_echo("hi"), SECRET) == (b"Error: token required\n", False)
        assert self._ask(b"quit_server", SECRET) == (b"Error: token required\n", False)

    def test_envelope_token_command_and_quit(self):
        command = [["echo", {"value": "ok"}]]
        good = json.dumps({"token": SECRET, "command": command}).encode()
        bad = json.dumps({"token": "nope", "command": command}).encode()
        assert self._ask(good, SECRET) == (b"ok\n" + END, False)
        assert self._ask(bad, SECRET) == (b"Error: unauthorised\n", False)
        assert self._ask(json.dumps({"token": SECRET, "op": "quit"}).encode(), SECRET) == \
            (b"Server shutting down\n", True)
        assert self._ask(json.dumps({"token": SECRET}).encode(), SECRET) == (END, False)
        assert self._ask(json.dumps({"command": command}).encode()) == (b"ok\n" + END, False)


def test_secret_matches_needs_a_string():
    assert secret_matches("a", "a") and not secret_matches("b", "a") and not secret_matches(None, "a")


def test_server_tls_context_pins_tls_1_2_and_loads_the_chain(monkeypatch):
    loaded = []
    monkeypatch.setattr(ssl.SSLContext, "load_cert_chain",
                        lambda self, certfile, keyfile: loaded.append((certfile, keyfile)))
    context = server_tls_context("cert.pem", "key.pem")
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2
    assert loaded == [("cert.pem", "key.pem")]
