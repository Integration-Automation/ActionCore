"""
The TCP action server: one JSON action document per connection, one reply line per record, then
``Return_Data_Over_JE``.

:class:`ActionRequestHandler` is a template. The steps are: read the request (one ``recv``, or a 4-byte
length-prefixed frame), decode it, then handle ``quit_server`` or parse, check and run the document and reply.
Each step is a method a dialect can override (see :mod:`je_action_core.socket_auth`). What the replies say is
set by :class:`ReplyMessages`. There is no authentication in the base handler: bind it to a trusted interface,
or use a dialect with a secret.
"""
from __future__ import annotations

import json
import socketserver
import ssl
import struct
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, Optional, Tuple, Type

END_MARKER: str = "Return_Data_Over_JE"
QUIT_COMMAND: str = "quit_server"
MAX_PAYLOAD_BYTES: int = 8192
MAX_FRAME_BYTES: int = 1 << 20  # 1 MiB
_FRAME_HEADER = struct.Struct("!I")
_NEWLINE: bytes = b"\n"


def _discard(_message: str) -> None:
    """Default log hook: report nothing."""


class OversizePolicy(Enum):
    """What happens to an unframed payload that fills the receive buffer."""

    READ_PREFIX = "read_prefix"  # parse what arrived (a cut-off document then fails as invalid JSON)
    REJECT = "reject"  # drop it without a reply


class Framing(Enum):
    """How a request and its reply are delimited on the wire."""

    RAW = "raw"  # one recv of MAX_PAYLOAD_BYTES; the reply is written as it is
    LENGTH_PREFIX = "length_prefix"  # a 4-byte big-endian length, then the body; every reply line is one frame


class FailureStage(Enum):
    """Where a request failed; picks the :class:`ReplyMessages` template."""

    JSON = "json"
    REFUSED = "refused"  # the validate hook raised
    EXECUTE = "execute"


@dataclass(frozen=True)
class ReplyMessages:
    """
    ``str.format`` templates for what the server says; ``None`` means "say nothing".

    ``record`` gets ``key`` and ``value``; the failure templates get ``error``; ``log_command`` gets ``text`` and
    ``size``. ``json_error`` and ``refused`` fall back to ``error`` when ``None``. ``{value!s}`` is ``str(value)``;
    a bare ``{value}`` is ``format(value)``, which differs for a few types (``IntEnum``).
    """

    record: str = "{value!s}"
    error: str = "{error!s}"
    json_error: Optional[str] = None
    refused: Optional[str] = None
    decode_error: Optional[str] = None  # None: an undecodable request is logged and dropped
    quit: Optional[str] = None
    auth_required: str = "auth error"
    auth_refused: str = "auth error"
    log_command: str = "command is: {text}"


@dataclass(frozen=True)
class SocketServerSettings:
    """
    :param execute: runs the decoded document and returns its records (an executor's ``execute_action``).
    :param validate: checks the decoded document first; raise to refuse it.
    :param handled: errors answered with a failure reply; any other error ends the connection.
    :param secret: the shared secret of an authenticating dialect (``None``: no authentication).
    :param tls_context: wraps every connection server-side (see :func:`server_tls_context`).
    :param recv_timeout: seconds a connection may stay silent (``None``: no limit).
    """

    execute: Callable[[Any], Mapping[str, Any]]
    validate: Optional[Callable[[Any], None]] = None
    handled: Tuple[Type[BaseException], ...] = (Exception,)
    oversize: OversizePolicy = OversizePolicy.READ_PREFIX
    framing: Framing = Framing.RAW
    decode_errors: str = "strict"
    messages: ReplyMessages = field(default_factory=ReplyMessages)
    secret: Optional[str] = None
    auth_prefix: str = "AUTH "
    tls_context: Optional[ssl.SSLContext] = None
    recv_timeout: Optional[float] = None
    log_info: Callable[[str], None] = _discard
    log_error: Callable[[str], None] = _discard


def server_tls_context(certfile: str, keyfile: str) -> ssl.SSLContext:
    """A server-side TLS context with the standard library's hardened defaults and TLS 1.2 or later."""
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=certfile, keyfile=keyfile)
    return context


class ActionRequestHandler(socketserver.BaseRequestHandler):
    """Handles one connection of an :class:`ActionTCPServer` (APITestka's and MailThunder's dialect)."""

    server: ActionTCPServer
    connection: Any
    # A dialect sets this when a connection that sent nothing at all (before stripping) gets no reply;
    # here an empty request is parsed like any other and answered with the JSON error.
    IGNORE_EMPTY_REQUEST: bool = False

    @property
    def settings(self) -> SocketServerSettings:
        """The server's settings."""
        return self.server.settings

    def handle(self) -> None:
        """Read one request, then answer it (see the module docstring)."""
        if not self.secure():
            return
        if self.settings.recv_timeout is not None:
            self.connection.settimeout(self.settings.recv_timeout)
        raw = self.read_request()
        if raw is None:
            return
        text = self.decode(raw)
        if text is not None:
            self.process(text)

    def secure(self) -> bool:
        """Wrap the connection in TLS when the settings ask for it; False when the handshake failed."""
        self.connection = self.request
        context = self.settings.tls_context
        if context is None:
            return True
        try:
            self.connection = context.wrap_socket(self.request, server_side=True)
        except (ssl.SSLError, OSError) as error:
            self.settings.log_error(f"TLS handshake failed: {error}")
            return False
        return True

    def read_request(self) -> Optional[bytes]:
        """The request with surrounding whitespace stripped, or ``None`` to end the connection silently."""
        if self.settings.framing is Framing.LENGTH_PREFIX:
            body = self._read_frame()
            return None if body is None else body.strip()
        raw = self.connection.recv(MAX_PAYLOAD_BYTES)
        if not raw and self.IGNORE_EMPTY_REQUEST:
            return None
        raw = raw.strip()
        if self.settings.oversize is OversizePolicy.REJECT and len(raw) >= MAX_PAYLOAD_BYTES:
            self.settings.log_error("payload exceeds max buffer size; rejected")
            return None
        return raw

    def _read_frame(self) -> Optional[bytes]:
        header = self._read_exact(_FRAME_HEADER.size)
        if header is None:
            return None
        (length,) = _FRAME_HEADER.unpack(header)
        if length == 0 or length > MAX_FRAME_BYTES:
            return None
        return self._read_exact(length)

    def _read_exact(self, size: int) -> Optional[bytes]:
        buffer = bytearray()
        while len(buffer) < size:
            chunk = self.connection.recv(size - len(buffer))
            if not chunk:
                return None
            buffer.extend(chunk)
        return bytes(buffer)

    def decode(self, raw: bytes) -> Optional[str]:
        """The request as text, or ``None`` after an undecodable one was logged (and answered, if configured)."""
        try:
            return str(raw, encoding="utf-8", errors=self.settings.decode_errors)
        except UnicodeDecodeError as error:
            self.settings.log_error(repr(error))
            template = self.settings.messages.decode_error
            if template is not None:
                self._reply_and_end(template.format(error=error))
            return None

    def process(self, text: str) -> None:
        """Log the request, then quit or run it."""
        self.settings.log_info(self.settings.messages.log_command.format(text=text, size=len(text)))
        if text == QUIT_COMMAND:
            self.on_quit()
            return
        self.run_text(text)

    def run_text(self, text: str) -> None:
        """Parse ``text`` as JSON and run it."""
        try:
            document = json.loads(text)
        except self.settings.handled as error:
            self.reply_failure(FailureStage.JSON, error)
            return
        self.run_document(document)

    def run_document(self, document: Any) -> None:
        """Check, run and answer one decoded document."""
        try:
            if self.settings.validate is not None:
                self.settings.validate(document)
        except self.settings.handled as error:
            self.reply_failure(FailureStage.REFUSED, error)
            return
        try:
            for key, value in self.settings.execute(document).items():
                self.write_line(self.settings.messages.record.format(key=key, value=value))
            self.write_end()
        except self.settings.handled as error:
            self.reply_failure(FailureStage.EXECUTE, error)

    def reply_failure(self, stage: FailureStage, error: BaseException) -> None:
        """Log ``error`` and answer it with the template for ``stage``, then the end marker."""
        self.settings.log_error(repr(error))
        messages = self.settings.messages
        template = {FailureStage.JSON: messages.json_error, FailureStage.REFUSED: messages.refused}.get(stage)
        self._reply_and_end((template or messages.error).format(error=error))

    def on_quit(self) -> None:
        """Stop the server; answer only when the settings give a quit reply."""
        self.server.request_stop()
        if self.settings.messages.quit is not None:
            self.write_line(self.settings.messages.quit)
        self.settings.log_info("Now quit server")

    def _reply_and_end(self, text: str) -> None:
        try:
            self.write_line(text)
            self.write_end()
        except OSError as send_error:
            self.settings.log_error(repr(send_error))

    def write_line(self, text: str) -> None:
        """Send ``text`` and a newline (one frame when framed)."""
        self.write(text.encode("utf-8") + _NEWLINE)

    def write_end(self) -> None:
        """Send the end marker and a newline."""
        self.write(END_MARKER.encode("utf-8") + _NEWLINE)

    def write(self, data: bytes) -> None:
        """Send ``data`` as it is, or as one length-prefixed frame."""
        if self.settings.framing is Framing.LENGTH_PREFIX:
            data = _FRAME_HEADER.pack(len(data)) + data
        self.connection.sendall(data)


class ActionTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """
    A threading TCP server. ``close_flag`` turns True, and ``close_event`` is set, once a client asks it to quit.
    """

    def __init__(self, server_address: Tuple[str, int], settings: SocketServerSettings,
                 request_handler_class: Type[socketserver.BaseRequestHandler] = ActionRequestHandler) -> None:
        super().__init__(server_address, request_handler_class)
        self.settings = settings
        self.close_flag: bool = False
        self.close_event = threading.Event()

    def request_stop(self) -> None:
        """Mark the server closed and stop ``serve_forever`` from a helper thread (safe inside a handler)."""
        self.close_flag = True
        self.close_event.set()
        threading.Thread(target=self.shutdown, daemon=True).start()


def start_action_socket_server(host: str, port: int, settings: SocketServerSettings,
                               handler_class: Type[socketserver.BaseRequestHandler] = ActionRequestHandler,
                               server_class: Type[ActionTCPServer] = ActionTCPServer) -> ActionTCPServer:
    """Bind exactly ``host`` and ``port``, serve on a daemon thread and return the server."""
    server = server_class((host, port), settings, handler_class)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    return server
