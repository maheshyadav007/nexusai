import json
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog

from nexusai.contracts.models import (
    AvailableModel,
    AvailableModels,
    CancelModelLogin,
    DisconnectModel,
    GetModelProvider,
    GetModelStatus,
    ListModels,
    ListProviderModels,
    ModelLogin,
    ModelProviderView,
    ModelReply,
    ModelsChanged,
    ModelStatus,
    SaveModelProvider,
    SelectModel,
    StartModelLogin,
    TestModel,
)
from nexusai.contracts.notifications import NotificationRequested
from nexusai.kernel.database import Migration
from nexusai.kernel.module import CommandError, Context, Module
from nexusai.kernel.secrets import secret_store
from nexusai.modules.models.chatgpt import (
    ChatGptClient,
    ChatGptError,
    DeviceCode,
    SignInRequired,
    Tokens,
    account_email,
    is_expiring,
    plan_type,
)

log = structlog.get_logger()
TOKENS = "chatgpt.tokens"
LITELLM_KEY = "litellm.key"

models_module = Module(
    name="models",
    migrations=[
        Migration(
            "models_001",
            "CREATE TABLE model_selection (provider TEXT PRIMARY KEY, model TEXT NOT NULL)",
        ),
        Migration(
            "models_002",
            "CREATE TABLE model_provider_settings ("
            " id INTEGER PRIMARY KEY CHECK (id = 1), value TEXT NOT NULL)",
        ),
    ],
)


@dataclass
class _Login:
    """The sign-in in progress, in memory: after a restart the user just starts again."""

    state: ModelLogin = field(default_factory=lambda: ModelLogin(state="idle"))
    stop: threading.Event | None = None


_login = _Login()
_login_lock = threading.Lock()
# Renewing can replace the refresh token, so two renewals at once could sign the user out.
_refresh_lock = threading.Lock()


def reset_login() -> None:
    with _login_lock:
        if _login.stop:
            _login.stop.set()
        _login.state = ModelLogin(state="idle")
        _login.stop = None


def _announce(ctx: Context, change: str) -> None:
    with ctx.bus.unit_of_work() as work:
        work.emit(
            "models.changed",
            ModelsChanged.model_validate({"change": change}).model_dump(),
            source=models_module.name,
            trace_id=ctx.trace_id,
        )


def _stored_tokens(ctx: Context) -> Tokens | None:
    value = secret_store(ctx.config.secrets_test_file).get(TOKENS)
    return Tokens.from_json(value) if value else None


def _forget_tokens(ctx: Context) -> None:
    secret_store(ctx.config.secrets_test_file).delete(TOKENS)


def _sign_in_ended(ctx: Context) -> None:
    _forget_tokens(ctx)
    with ctx.bus.unit_of_work() as work:
        work.emit(
            "models.changed",
            ModelsChanged(change="disconnected").model_dump(),
            source=models_module.name,
            trace_id=ctx.trace_id,
        )
        work.emit(
            "notification.requested",
            NotificationRequested(
                kind="model",
                title="ChatGPT was disconnected",
                detail="Your sign-in ended. Connect ChatGPT again in Settings.",
                link="/settings?section=models",
            ).model_dump(),
            source=models_module.name,
            trace_id=ctx.trace_id,
        )


def _fresh_tokens(ctx: Context, client: ChatGptClient, *, force: bool = False) -> Tokens:
    """A usable access token, renewed if it's about to expire."""
    with _refresh_lock:
        tokens = _stored_tokens(ctx)
        if tokens is None:
            raise CommandError("models.not_connected", "Connect ChatGPT first.", 409)
        if not force and not is_expiring(
            tokens.access_token, ctx.config.chatgpt.refresh_skew_seconds
        ):
            return tokens
        try:
            renewed = client.refresh(tokens)
        except SignInRequired as error:
            _sign_in_ended(ctx)
            raise CommandError("models.sign_in_required", str(error), 401) from error
        except ChatGptError as error:
            raise CommandError("models.unavailable", str(error), 502) from error
        secret_store(ctx.config.secrets_test_file).set(TOKENS, renewed.to_json())
        return renewed


def _with_token[T](ctx: Context, call: Callable[[ChatGptClient, str], T]) -> T:
    """Runs a call with a fresh token, renewing once if ChatGPT says the token has ended."""
    client = ChatGptClient(ctx.config.chatgpt)
    try:
        try:
            return call(client, _fresh_tokens(ctx, client).access_token)
        except SignInRequired:
            return call(client, _fresh_tokens(ctx, client, force=True).access_token)
    except SignInRequired as error:
        _sign_in_ended(ctx)
        raise CommandError("models.sign_in_required", str(error), 401) from error
    except ChatGptError as error:
        raise CommandError("models.unavailable", str(error), 502) from error


def _selected(ctx: Context) -> str | None:
    rows = ctx.bus.db.fetch_all(
        "SELECT model FROM model_selection WHERE provider = ?", ("chatgpt",)
    )
    return rows[0]["model"] if rows else None


def _status(ctx: Context) -> ModelStatus:
    with _login_lock:
        login = _login.state
    tokens = _stored_tokens(ctx)
    if tokens is None:
        return ModelStatus(connected=False, login=login)
    return ModelStatus(
        connected=True,
        account_email=account_email(tokens.access_token),
        plan=plan_type(tokens.access_token),
        selected_model=_selected(ctx),
        login=login,
    )


def _poll_login(
    ctx: Context, client: ChatGptClient, stop: threading.Event, code: DeviceCode
) -> None:
    deadline = time.monotonic() + ctx.config.chatgpt.login_timeout_seconds
    failure: str
    try:
        while time.monotonic() < deadline:
            if stop.wait(code.interval):
                return
            tokens = client.poll_device_code(code)
            if tokens is None:
                continue
            if stop.is_set():
                return
            secret_store(ctx.config.secrets_test_file).set(TOKENS, tokens.to_json())
            with _login_lock:
                _login.state = ModelLogin(state="idle")
                _login.stop = None
            _announce(ctx, "connected")
            return
        failure = "The sign-in code expired. Start again to get a new one."
    except ChatGptError as error:
        failure = str(error)
    except Exception:
        log.exception("chatgpt_login_failed")
        failure = "Sign-in hit a problem. Try again."
    if stop.is_set():
        return
    with _login_lock:
        _login.state = ModelLogin(state="failed", error=failure)
        _login.stop = None
    _announce(ctx, "login_failed")


def chatgpt_events(ctx: Context, body: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """ChatGPT's reply as it arrives. A rejected token is renewed once, before anything streams."""
    client = ChatGptClient(ctx.config.chatgpt)

    def access_token(*, force: bool = False) -> str:
        try:
            return _fresh_tokens(ctx, client, force=force).access_token
        except CommandError as error:
            raise SignInRequired(error.message) from error

    stream = client.stream_events(access_token(), body)
    try:
        first = next(stream, None)
    except SignInRequired:
        stream = client.stream_events(access_token(force=True), body)
        try:
            first = next(stream, None)
        except SignInRequired:
            _sign_in_ended(ctx)
            raise
    if first is not None:
        yield first
        yield from stream


@dataclass(frozen=True)
class ActiveModel:
    provider: str
    model: str | None
    base_url: str | None
    supports_tools: bool


def _provider_row(ctx: Context) -> dict[str, Any]:
    rows = ctx.bus.db.fetch_all("SELECT value FROM model_provider_settings")
    return json.loads(rows[0]["value"]) if rows else {"provider": "chatgpt"}


def active_settings(ctx: Context) -> ActiveModel:
    raw = _provider_row(ctx)
    provider = raw.get("provider", "chatgpt")
    if provider == "litellm":
        return ActiveModel(
            "litellm", raw.get("model"), raw.get("base_url"), bool(raw.get("supports_tools"))
        )
    return ActiveModel("chatgpt", _selected(ctx), None, True)


def litellm_key(ctx: Context) -> str | None:
    return secret_store(ctx.config.secrets_test_file).get(LITELLM_KEY)


def _save_provider(ctx: Context, values: dict[str, Any]) -> None:
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "INSERT INTO model_provider_settings (id, value) VALUES (1, ?)"
            " ON CONFLICT (id) DO UPDATE SET value = excluded.value",
            (json.dumps(values),),
        )
        work.emit(
            "models.changed",
            ModelsChanged(change="selected").model_dump(),
            source=models_module.name,
            trace_id=ctx.trace_id,
        )


def _provider_view(ctx: Context) -> ModelProviderView:
    raw = _provider_row(ctx)
    return ModelProviderView(
        provider=raw.get("provider", "chatgpt"),
        base_url=raw.get("base_url"),
        model=raw.get("model"),
        supports_tools=bool(raw.get("supports_tools")),
        has_key=litellm_key(ctx) is not None,
    )


@models_module.query("models.provider")
def get_provider(query: GetModelProvider, ctx: Context) -> ModelProviderView:
    return _provider_view(ctx)


@models_module.command("models.provider.save")
def save_provider(command: SaveModelProvider, ctx: Context) -> ModelProviderView:
    if command.provider == "litellm" and command.base_url:
        parsed = urlparse(command.base_url)
        local = parsed.hostname in {"127.0.0.1", "localhost"}
        if parsed.scheme != "https" and not local:
            raise CommandError(
                "models.not_encrypted", "Use an https:// address for the model server.", 422
            )
    if command.api_key:
        secret_store(ctx.config.secrets_test_file).set(LITELLM_KEY, command.api_key)
    _save_provider(
        ctx,
        {
            "provider": command.provider,
            "base_url": command.base_url,
            "model": command.model,
            "supports_tools": command.supports_tools,
        },
    )
    return _provider_view(ctx)


@models_module.command("models.provider.listModels")
def list_provider_models(command: ListProviderModels, ctx: Context) -> AvailableModels:
    key = command.api_key or litellm_key(ctx)
    if not key:
        raise CommandError("models.no_key", "Enter the API key first.", 422)
    try:
        response = httpx.get(
            f"{command.base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=ctx.config.network_check_timeout_seconds,
        )
        response.raise_for_status()
        names = sorted(str(item["id"]) for item in response.json().get("data", []))
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        raise CommandError(
            "models.unreachable",
            "Couldn't list models from that server. Check the address and key.",
            502,
        ) from error
    return AvailableModels(models=[AvailableModel(id=name, name=name) for name in names])


@models_module.query("models.status")
def get_status(query: GetModelStatus, ctx: Context) -> ModelStatus:
    return _status(ctx)


@models_module.command("models.login.start")
def start_login(command: StartModelLogin, ctx: Context) -> ModelStatus:
    client = ChatGptClient(ctx.config.chatgpt)
    with _login_lock:
        waiting = _login.state.state == "waiting"
    if waiting:
        return _status(ctx)
    try:
        code = client.request_device_code()
    except ChatGptError as error:
        with _login_lock:
            _login.state = ModelLogin(state="failed", error=str(error))
        _announce(ctx, "login_failed")
        return _status(ctx)
    stop = threading.Event()
    with _login_lock:
        _login.state = ModelLogin(
            state="waiting", user_code=code.user_code, verification_url=client.verification_url
        )
        _login.stop = stop
    threading.Thread(target=_poll_login, args=(ctx, client, stop, code), daemon=True).start()
    _announce(ctx, "login_started")
    return _status(ctx)


@models_module.command("models.login.cancel")
def cancel_login(command: CancelModelLogin, ctx: Context) -> ModelStatus:
    reset_login()
    _announce(ctx, "login_cancelled")
    return _status(ctx)


@models_module.command("models.disconnect")
def disconnect(command: DisconnectModel, ctx: Context) -> ModelStatus:
    reset_login()
    _forget_tokens(ctx)
    with ctx.bus.unit_of_work() as work:
        work.tx.execute("DELETE FROM model_selection WHERE provider = ?", ("chatgpt",))
        work.emit(
            "models.changed",
            ModelsChanged(change="disconnected").model_dump(),
            source=models_module.name,
            trace_id=ctx.trace_id,
        )
    return _status(ctx)


def _forget(ctx: Context) -> None:
    store = secret_store(ctx.config.secrets_test_file)
    store.delete(TOKENS)
    store.delete(LITELLM_KEY)


models_module.on_reset.append(_forget)


@models_module.query("models.list")
def list_models(query: ListModels, ctx: Context) -> AvailableModels:
    pairs = _with_token(ctx, lambda client, token: client.list_models(token))
    return AvailableModels(models=[AvailableModel(id=i, name=n) for i, n in pairs])


@models_module.command("models.select")
def select_model(command: SelectModel, ctx: Context) -> ModelStatus:
    pairs = _with_token(ctx, lambda client, token: client.list_models(token))
    if command.model not in {model_id for model_id, _ in pairs}:
        raise CommandError("models.not_available", "Your plan doesn't offer that model.", 422)
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "INSERT INTO model_selection (provider, model) VALUES (?, ?)"
            " ON CONFLICT (provider) DO UPDATE SET model = excluded.model",
            ("chatgpt", command.model),
        )
        work.emit(
            "models.changed",
            ModelsChanged(change="selected").model_dump(),
            source=models_module.name,
            trace_id=ctx.trace_id,
        )
    return _status(ctx)


@models_module.command("models.test")
def test_model(command: TestModel, ctx: Context) -> ModelReply:
    """Sends only the text the user typed. Mail and files never reach this."""
    model = _selected(ctx)
    if model is None:
        raise CommandError("models.none_selected", "Choose a model first.", 409)

    def call(client: ChatGptClient, token: str) -> str:
        parts = client.stream_reply(
            token, model, ctx.config.chatgpt.test_instructions, command.prompt
        )
        return "".join(parts)

    text = _with_token(ctx, call)
    if not text.strip():
        raise CommandError("models.empty_reply", "ChatGPT sent an empty reply. Try again.", 502)
    return ModelReply(model=model, text=text)
