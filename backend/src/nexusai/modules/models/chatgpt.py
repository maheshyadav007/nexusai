"""Signs in with a ChatGPT subscription and calls its models.

This is the Codex device-code sign-in, as Hermes Agent and OpenClaw use it. OpenAI asks tools
outside Codex to identify themselves, so requests carry NexusAI's own name rather than Codex's.
"""

import base64
import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx

from nexusai import __version__
from nexusai.kernel.config import ChatGptConfig

AUTH_CLAIM = "https://api.openai.com/auth"
PROFILE_CLAIM = "https://api.openai.com/profile"
STILL_WAITING = {403, 404}


class ChatGptError(Exception):
    """The message is shown to the user, so it says what to do next."""


class SignInRequired(ChatGptError):
    pass


class ChatGptLimited(ChatGptError):
    pass


@dataclass(frozen=True)
class DeviceCode:
    device_auth_id: str
    user_code: str
    interval: float


@dataclass(frozen=True)
class Tokens:
    access_token: str
    refresh_token: str

    def to_json(self) -> str:
        return json.dumps({"access_token": self.access_token, "refresh_token": self.refresh_token})

    @classmethod
    def from_json(cls, value: str) -> "Tokens":
        raw = json.loads(value)
        return cls(raw["access_token"], raw["refresh_token"])


def claims(access_token: str) -> dict[str, Any]:
    """Reads the token's contents for display and routing. The server is what verifies it."""
    try:
        payload = access_token.split(".")[1]
        decoded = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def account_email(access_token: str) -> str | None:
    email = claims(access_token).get(PROFILE_CLAIM, {}).get("email")
    return email if isinstance(email, str) else None


def plan_type(access_token: str) -> str | None:
    plan = claims(access_token).get(AUTH_CLAIM, {}).get("chatgpt_plan_type")
    return plan if isinstance(plan, str) else None


def is_expiring(access_token: str, skew_seconds: float) -> bool:
    expires = claims(access_token).get("exp")
    return not isinstance(expires, (int, float)) or expires - time.time() <= skew_seconds


class ChatGptClient:
    def __init__(self, config: ChatGptConfig) -> None:
        self.config = config
        self.http = httpx.Client(
            timeout=config.timeout_seconds,
            headers={"User-Agent": f"NexusAI/{__version__}", "originator": config.originator},
        )

    @property
    def verification_url(self) -> str:
        return f"{self.config.issuer}/codex/device"

    def _post_login(self, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return self.http.post(url, **kwargs)
        except httpx.HTTPError as error:
            raise ChatGptError(
                "Couldn't reach OpenAI. Check your internet connection or proxy, then try again."
            ) from error

    def request_device_code(self) -> DeviceCode:
        response = self._post_login(
            f"{self.config.issuer}/api/accounts/deviceauth/usercode",
            json={"client_id": self.config.client_id},
        )
        if response.status_code == 429:
            raise ChatGptError("OpenAI is limiting sign-in attempts. Wait a minute and try again.")
        if response.status_code != 200:
            raise ChatGptError(f"OpenAI refused the sign-in request (HTTP {response.status_code}).")
        data = response.json()
        interval = max(self.config.min_poll_seconds, float(data.get("interval", 5)))
        return DeviceCode(data["device_auth_id"], data["user_code"], interval)

    def poll_device_code(self, code: DeviceCode) -> Tokens | None:
        """None means the user hasn't finished signing in yet."""
        response = self._post_login(
            f"{self.config.issuer}/api/accounts/deviceauth/token",
            json={"device_auth_id": code.device_auth_id, "user_code": code.user_code},
        )
        if response.status_code in STILL_WAITING:
            return None
        if response.status_code != 200:
            raise ChatGptError(f"Sign-in stopped (HTTP {response.status_code}). Try again.")
        data = response.json()
        exchange = self._post_login(
            f"{self.config.issuer}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": data["authorization_code"],
                "redirect_uri": f"{self.config.issuer}/deviceauth/callback",
                "client_id": self.config.client_id,
                "code_verifier": data["code_verifier"],
            },
        )
        if exchange.status_code != 200:
            raise ChatGptError(f"Sign-in didn't finish (HTTP {exchange.status_code}). Try again.")
        tokens = exchange.json()
        return Tokens(tokens["access_token"], tokens["refresh_token"])

    def refresh(self, tokens: Tokens) -> Tokens:
        response = self._post_login(
            f"{self.config.issuer}/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens.refresh_token,
                "client_id": self.config.client_id,
            },
        )
        if response.status_code == 429:
            raise ChatGptError("OpenAI is limiting requests. Wait a minute and try again.")
        if response.status_code in {400, 401, 403}:
            raise SignInRequired("Your ChatGPT sign-in has ended. Connect ChatGPT again.")
        if response.status_code != 200:
            raise ChatGptError(f"Couldn't renew your sign-in (HTTP {response.status_code}).")
        data = response.json()
        # OpenAI may issue a new refresh token, and the old one then stops working.
        return Tokens(data["access_token"], data.get("refresh_token") or tokens.refresh_token)

    def _account_headers(self, access_token: str) -> dict[str, str]:
        auth = claims(access_token).get(AUTH_CLAIM, {})
        headers = {"Authorization": f"Bearer {access_token}"}
        # Without the account ID, the model list comes back empty rather than failing.
        if account := auth.get("chatgpt_account_id"):
            headers["ChatGPT-Account-ID"] = account
        if residency := auth.get("chatgpt_data_residency") or auth.get("chatgpt_compute_residency"):
            headers["x-openai-internal-codex-residency"] = residency
        return headers

    def list_models(self, access_token: str) -> list[tuple[str, str]]:
        """The (id, name) pairs this account can use, best first. Empty if none are offered."""
        for version in self.config.model_list_client_versions:
            entries = self._fetch_model_entries(access_token, version)
            if entries:
                return entries
        return []

    def _fetch_model_entries(self, access_token: str, version: str) -> list[tuple[str, str]]:
        try:
            response = self.http.get(
                f"{self.config.base_url}/models",
                params={"client_version": version},
                headers=self._account_headers(access_token),
            )
        except httpx.HTTPError as error:
            raise ChatGptError("Couldn't reach ChatGPT. Check your connection.") from error
        _raise_for_status(response)
        ranked = []
        for entry in response.json().get("models", []):
            slug = entry.get("slug")
            if not slug or str(entry.get("visibility", "")).lower() in {"hide", "hidden"}:
                continue
            priority = entry.get("priority")
            rank = priority if isinstance(priority, (int, float)) else float("inf")
            ranked.append((rank, slug, entry.get("display_name") or slug))
        ranked.sort(key=lambda item: (item[0], item[1]))
        return [(slug, name) for _, slug, name in ranked]

    def stream_reply(
        self, access_token: str, model: str, instructions: str, prompt: str
    ) -> Iterator[str]:
        body = {
            "model": model,
            "instructions": instructions,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            "store": False,
            "stream": True,
        }
        for event in self.stream_events(access_token, body):
            if event.get("type") == "response.output_text.delta":
                yield event.get("delta", "")

    def stream_events(self, access_token: str, body: dict[str, Any]) -> Iterator[dict[str, Any]]:
        headers = {**self._account_headers(access_token), "Accept": "text/event-stream"}
        try:
            with self.http.stream(
                "POST", f"{self.config.base_url}/responses", json=body, headers=headers
            ) as response:
                if response.status_code != 200:
                    response.read()
                _raise_for_status(response)
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    event = json.loads(line[5:].strip())
                    kind = event.get("type")
                    if kind in {"response.failed", "error"}:
                        detail = (event.get("response") or event).get("error") or {}
                        raise ChatGptError(
                            detail.get("message") or "ChatGPT couldn't answer. Try again."
                        )
                    yield event
        except httpx.HTTPError as error:
            raise ChatGptError("The connection to ChatGPT dropped. Try again.") from error


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code == 200:
        return
    if response.status_code == 401:
        raise SignInRequired("Your ChatGPT sign-in has ended. Connect ChatGPT again.")
    if response.status_code == 429:
        raise ChatGptLimited("You've reached your ChatGPT plan's limit for now. Try again later.")
    if response.status_code == 403:
        raise ChatGptError("ChatGPT refused this request. Your plan may not include this model.")
    raise ChatGptError(f"ChatGPT returned an error (HTTP {response.status_code}). Try again.")
