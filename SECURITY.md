# Security policy

## Supported versions

Security fixes are provided for the latest release and the default
branch. Older releases are not supported. Upgrade before reporting
an issue that may already be fixed.

## Reporting a vulnerability

Do not open a public issue, pull request, or discussion for a suspected
vulnerability.

Use either private channel:

- **GitHub Security Advisories.** Open a private report from this
  repository's Security tab, **Report a vulnerability**. This is the
  preferred channel.
- **Email.** `jechenmailman@gmail.com`, with a subject line that begins
  with `[SECURITY]`.

Include the affected version, platform, impact, and steps to reproduce.
Do not attach credentials, tokens, or unredacted logs.

The maintainers aim to acknowledge a report within 5 business days, and
to coordinate a fix and disclosure within 90 days. There is no bug-bounty
promise.

## Operational notes

Action files are operator-trusted UTF-8 JSON. The expression allowlist
excludes names that execute code, read files, or read standard input.

Until a host closes the package gate, an action list can still import an
arbitrary package; the loader warns and continues. A host that needs a closed
gate must call ``set_allow_arbitrary_packages(False)`` before it loads
actions. Do not expose ``allow_packages`` or ``set_allow_arbitrary_packages``
as action commands.

The socket handler does not authenticate clients. Bind the host the caller
supplies. Do not listen on all interfaces unless that exposure is intentional.
