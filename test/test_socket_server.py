import json
import socket
import time

import pytest

from je_action_core import (
    END_MARKER,
    MAX_PAYLOAD_BYTES,
    QUIT_COMMAND,
    OversizePolicy,
    SocketServerSettings,
    start_action_socket_server,
)

_TIMEOUT_SECONDS = 10


def _ask(port: int, payload: bytes) -> str:
    with socket.create_connection(("127.0.0.1", port), timeout=_TIMEOUT_SECONDS) as client:
        client.sendall(payload)
        chunks = []
        chunk = client.recv(4096)
        while chunk:  # the server closes the connection after its reply
            chunks.append(chunk)
            chunk = client.recv(4096)
    return b"".join(chunks).decode("utf-8")


@pytest.fixture
def server_factory():
    servers = []

    def start(**settings):
        settings.setdefault("execute", lambda document: {f"execute: {action}": len(action) for action in document})
        server = start_action_socket_server("127.0.0.1", 0, SocketServerSettings(**settings))
        servers.append(server)
        return server, server.server_address[1]
    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def test_replies_each_value_then_the_marker(server_factory):
    _server, port = server_factory()
    assert _ask(port, json.dumps([["a"], ["b", 1]]).encode()) == f"1\n2\n{END_MARKER}\n"


def test_errors_reply_with_their_text(server_factory):
    logged = []
    _server, port = server_factory(log_error=logged.append)
    reply = _ask(port, b"{not json")
    assert reply.endswith(f"{END_MARKER}\n") and "Expecting" in reply
    assert logged and logged[0].startswith("JSONDecodeError(")


def test_validation_runs_before_the_executor(server_factory):
    executed = []

    def refuse(document):
        raise ValueError("refused")
    _server, port = server_factory(validate=refuse, execute=lambda document: executed.append(document) or {})
    assert _ask(port, b"[]") == f"refused\n{END_MARKER}\n"
    assert executed == []


def test_quit_server_sets_the_close_flag(server_factory):
    server, port = server_factory()
    with socket.create_connection(("127.0.0.1", port), timeout=_TIMEOUT_SECONDS) as client:
        client.sendall(QUIT_COMMAND.encode())
    deadline = time.monotonic() + _TIMEOUT_SECONDS
    while not server.close_flag and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.close_flag


def test_reject_policy_drops_oversized_payloads(server_factory):
    logged = []
    _server, port = server_factory(oversize=OversizePolicy.REJECT, log_error=logged.append)
    assert _ask(port, b'["' + b"a" * MAX_PAYLOAD_BYTES + b'"]') == ""
    assert logged == ["payload exceeds max buffer size; rejected"]


def test_undecodable_bytes_are_dropped(server_factory):
    logged = []
    _server, port = server_factory(log_error=logged.append)
    assert _ask(port, b"\xff\xfe") == ""
    assert logged[0].startswith("UnicodeDecodeError(")
