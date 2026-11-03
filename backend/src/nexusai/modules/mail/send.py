"""Builds and sends mail over SMTP, using the person's own account."""

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from nexusai.contracts.mail import Draft, MailProfile, Recipient

IMPLICIT_TLS_PORT = 465
HELLO_NAME = "[127.0.0.1]"


class SendFailed(Exception):
    """The message is shown to the user, and the draft is kept."""


def _addresses(recipients: list[Recipient]) -> str:
    return ", ".join(formataddr((r.name, r.address)) for r in recipients)


def build_message(
    draft: Draft,
    profile: MailProfile,
    sender_name: str,
    in_reply_to: str | None,
    references: list[str],
    *,
    draft_marker: str | None = None,
) -> EmailMessage:
    message = EmailMessage()
    address = profile.address or profile.auth.user
    message["From"] = formataddr((sender_name, address))
    if draft.to:
        message["To"] = _addresses(draft.to)
    if draft.cc:
        message["Cc"] = _addresses(draft.cc)
    message["Subject"] = draft.subject
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=address.rsplit("@", 1)[-1])
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
        message["References"] = " ".join([*references, in_reply_to])
    if draft_marker:
        message["X-NexusAI-Draft"] = draft_marker
    message.set_content(draft.body)
    return message


def _connect(profile: MailProfile, password: str, timeout: float) -> smtplib.SMTP:
    """A signed-in connection. The fixed hostname skips smtplib's slow lookup of this computer's
    name (seconds on some networks), and keeps that name from going to the server."""
    server = profile.smtp
    client: smtplib.SMTP
    if server.secure and server.port == IMPLICIT_TLS_PORT:
        client = smtplib.SMTP_SSL(
            server.host,
            server.port,
            local_hostname=HELLO_NAME,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
    else:
        client = smtplib.SMTP(server.host, server.port, local_hostname=HELLO_NAME, timeout=timeout)
    try:
        if server.secure and server.port != IMPLICIT_TLS_PORT:
            client.starttls(context=ssl.create_default_context())
        client.ehlo_or_helo_if_needed()
        # A company relay on port 25 often takes mail from its own network with no sign-in.
        if server.secure or client.has_extn("auth"):
            client.login(profile.auth.user, password)
    except BaseException:
        client.close()
        raise
    return client


def send(
    message: EmailMessage, draft: Draft, profile: MailProfile, password: str, timeout: float
) -> None:
    recipients = [r.address for r in [*draft.to, *draft.cc, *draft.bcc]]
    if not recipients:
        raise SendFailed("Add at least one recipient.")
    try:
        with _connect(profile, password, timeout) as client:
            client.send_message(
                message, from_addr=profile.address or profile.auth.user, to_addrs=recipients
            )
    except smtplib.SMTPAuthenticationError as error:
        raise SendFailed("The mail server refused the username or password.") from error
    except smtplib.SMTPRecipientsRefused as error:
        raise SendFailed(
            "The mail server refused those recipients. Check the addresses."
        ) from error
    except (smtplib.SMTPException, OSError) as error:
        raise SendFailed("Couldn't send. Your draft is saved, so you can try again.") from error


def test_smtp(profile: MailProfile, password: str, timeout: float) -> str | None:
    """None if it worked, or what went wrong in plain words."""
    try:
        with _connect(profile, password, timeout):
            return None
    except smtplib.SMTPAuthenticationError:
        return "The server refused that username or password."
    except (smtplib.SMTPException, OSError) as error:
        server = profile.smtp
        return f"Couldn't connect to {server.host}:{server.port}. {type(error).__name__}"
