"""
Authenticating dialects of :class:`~je_action_core.socket_server.ActionRequestHandler`.

* :class:`SecretHeaderRequestHandler`: when a secret is set, the request's first line must be
  ``<auth_prefix><secret>`` and the document follows it (FileAutomation: ``AUTH <secret>``).
* :class:`EnvelopeTokenRequestHandler`: the document may be an envelope
  ``{"token": ..., "command": ..., "op": "quit"}``; when a secret is set, only an envelope with that token
  runs (LoadDensity).

Secrets are compared in constant time. Both dialects give no reply to a connection that sent nothing.
"""
from __future__ import annotations

import hmac
import json
from typing import Any

from je_action_core.socket_server import QUIT_COMMAND, ActionRequestHandler, FailureStage

_ENVELOPE_KEYS = ("token", "command")


def secret_matches(supplied: Any, secret: str) -> bool:
    """True when ``supplied`` is a string equal to ``secret`` (constant-time comparison)."""
    return isinstance(supplied, str) and hmac.compare_digest(supplied, secret)


class SecretHeaderRequestHandler(ActionRequestHandler):
    """
    With ``settings.secret`` set, a request is ``<auth_prefix><secret>\\n<document>``; anything else is
    answered with ``messages.auth_refused`` and the end marker. Without a secret it behaves like the base handler.
    """

    IGNORE_EMPTY_REQUEST = True

    def process(self, text: str) -> None:
        """Check the header line, then log, quit or run the document after it."""
        secret = self.settings.secret
        if secret:
            document = self._authenticated(text, secret)
            if document is None:
                self.settings.log_error("authentication failed")
                self._reply_and_end(self.settings.messages.auth_refused)
                return
            text = document
        super().process(text)

    def _authenticated(self, text: str, secret: str) -> str | None:
        head, _, rest = text.partition("\n")
        prefix = self.settings.auth_prefix
        if not head.startswith(prefix) or not rest:
            return None
        if not secret_matches(head[len(prefix):].strip(), secret):
            return None
        return rest


class EnvelopeTokenRequestHandler(ActionRequestHandler):
    """
    ``{"token": ..., "command": [...]}`` runs ``command``; ``{"token": ..., "op": "quit"}`` stops the server.
    With ``settings.secret`` set, the token must match (``messages.auth_refused`` otherwise) and a bare
    document or ``quit_server`` is answered with ``messages.auth_required``. Neither refusal ends with the marker.
    """

    IGNORE_EMPTY_REQUEST = True

    def process(self, text: str) -> None:
        """Log, then handle ``quit_server``, the envelope, or a bare document."""
        settings = self.settings
        settings.log_info(settings.messages.log_command.format(text=text, size=len(text)))
        if text == QUIT_COMMAND:
            if settings.secret:
                self.write_line(settings.messages.auth_required)
            else:
                self.on_quit()
            return
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            self.reply_failure(FailureStage.JSON, error)
            return
        self._dispatch(payload)

    def _dispatch(self, payload: Any) -> None:
        settings = self.settings
        if isinstance(payload, dict) and any(key in payload for key in _ENVELOPE_KEYS):
            if settings.secret and not secret_matches(payload.get("token"), settings.secret):
                self.write_line(settings.messages.auth_refused)
                return
            if payload.get("op") == "quit":
                self.on_quit()
                return
            command = payload.get("command")
        elif settings.secret:
            self.write_line(settings.messages.auth_required)
            return
        else:
            command = payload
        if command is None:
            self.write_end()
            return
        self.run_document(command)
