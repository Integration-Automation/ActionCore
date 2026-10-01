"""
The plain TCP action server shared by APITestka and MailThunder.

A client sends one JSON action document per connection. The server replies with each record value on its own
line, then ``Return_Data_Over_JE``. A failure replies with the error text, then the same marker.
``quit_server`` stops the server. No authentication: bind it to a trusted interface only.
"""
from __future__ import annotations

import json
import socketserver
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Optional, Tuple, Type

END_MARKER: str = "Return_Data_Over_JE"
QUIT_COMMAND: str = "quit_server"
MAX_PAYLOAD_BYTES: int = 8192
_NEWLINE: bytes = b"\n"


def _discard(_message: str) -> None:
    """Default log hook: report nothing."""


class OversizePolicy(Enum):
    """What happens to a payload that fills the receive buffer."""

    READ_PREFIX = "read_prefix"  # parse what arrived (a cut-off document then fails as invalid JSON)
    REJECT = "reject"  # drop it without a reply


@dataclass(frozen=True)
class SocketServerSettings:
    """
    :param execute: runs the decoded document and returns its records (an executor's ``execute_action``).
    :param validate: checks the decoded document first; raise to refuse it.
    :param handled: errors answered with their text and the end marker; any other error ends the connection.
    """

    execute: Callable[[Any], Mapping[str, Any]]
    validate: Optional[Callable[[Any], None]] = None
    handled: Tuple[Type[BaseException], ...] = (Exception,)
    oversize: OversizePolicy = OversizePolicy.READ_PREFIX
    log_info: Callable[[str], None] = _discard
    log_error: Callable[[str], None] = _discard


class ActionRequestHandler(socketserver.BaseRequestHandler):
    """Handles one connection of an :class:`ActionTCPServer`."""

    server: ActionTCPServer

    def handle(self) -> None:
        """Receive one document, run it and reply (see the module docstring)."""
        settings = self.server.settings
        raw = self.request.recv(MAX_PAYLOAD_BYTES).strip()
        if settings.oversize is OversizePolicy.REJECT and len(raw) >= MAX_PAYLOAD_BYTES:
            settings.log_error("payload exceeds max buffer size; rejected")
            return
        try:
            command_string = str(raw, encoding="utf-8")
        except UnicodeDecodeError as error:
            settings.log_error(repr(error))
            return
        settings.log_info(f"command is: {command_string}")
        if command_string == QUIT_COMMAND:
            self.server.shutdown()
            self.server.close_flag = True
            settings.log_info("Now quit server")
            return
        try:
            document = json.loads(command_string)
            if settings.validate is not None:
                settings.validate(document)
            for value in settings.execute(document).values():
                self._send_line(str(value))
            self._send_line(END_MARKER)
        except settings.handled as error:
            settings.log_error(repr(error))
            self._reply_error(error)

    def _send_line(self, text: str) -> None:
        self.request.sendto(text.encode("utf-8"), self.client_address)
        self.request.sendto(_NEWLINE, self.client_address)

    def _reply_error(self, error: BaseException) -> None:
        try:
            self._send_line(str(error))
            self._send_line(END_MARKER)
        except OSError as send_error:
            self.server.settings.log_error(repr(send_error))


class ActionTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """A threading TCP server whose ``close_flag`` turns True once a client sends ``quit_server``."""

    def __init__(self, server_address: Tuple[str, int], settings: SocketServerSettings,
                 request_handler_class: Type[socketserver.BaseRequestHandler] = ActionRequestHandler) -> None:
        super().__init__(server_address, request_handler_class)
        self.settings = settings
        self.close_flag: bool = False


def start_action_socket_server(host: str, port: int, settings: SocketServerSettings) -> ActionTCPServer:
    """Bind exactly ``host`` and ``port``, serve on a daemon thread and return the server."""
    server = ActionTCPServer((host, port), settings)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    return server
