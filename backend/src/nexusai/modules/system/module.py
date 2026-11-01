import os
import platform
import shutil
from urllib.parse import urlparse

import httpx

from nexusai import __version__
from nexusai.contracts.system import (
    CheckNetwork,
    Diagnostics,
    GetDiagnostics,
    GetTrace,
    LogLines,
    NetworkCheck,
    NetworkChecks,
    SearchLogs,
    TraceView,
)
from nexusai.kernel.logging import sink
from nexusai.kernel.module import Context, Module

system_module = Module(name="system")
PROXY_VARIABLES = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY")


def _proxy_host() -> str | None:
    """The proxy's host only, because the full value can hold a username and password."""
    for name in PROXY_VARIABLES:
        if value := os.environ.get(name):
            return urlparse(value).hostname or "set"
    return None


@system_module.query("logs.search")
def search_logs(query: SearchLogs, ctx: Context) -> LogLines:
    return LogLines(
        lines=sink.search(level=query.level, text=query.text, limit=ctx.config.log_page_size)
    )


@system_module.query("trace.get")
def get_trace(query: GetTrace, ctx: Context) -> TraceView:
    rows = ctx.bus.db.fetch_all("SELECT seq FROM events WHERE trace_id = ?", (query.trace_id,))
    seqs = {row["seq"] for row in rows}
    first = min(seqs, default=None)
    events = [
        event.model_dump(mode="json")
        for event in (ctx.bus.events_since(first - 1) if first else [])
        if event.seq in seqs
    ]
    lines = sink.search(trace_id=query.trace_id, limit=ctx.config.log_page_size)
    return TraceView(events=events, lines=list(reversed(lines)))


@system_module.query("diagnostics.get")
def get_diagnostics(query: GetDiagnostics, ctx: Context) -> Diagnostics:
    home = ctx.config.home
    database = ctx.config.database_path
    size = database.stat().st_size if database.exists() else 0
    free = shutil.disk_usage(home).free
    count = int(ctx.bus.db.fetch_all("SELECT COUNT(*) AS n FROM events")[0]["n"])
    failed = len(ctx.bus.failed_events())
    proxy = _proxy_host()
    system = f"{platform.system()} {platform.release()} {platform.machine()}"
    # Safe to paste into a support ticket: no secrets, addresses or mail.
    report = "\n".join(
        [
            f"NexusAI {__version__}",
            f"System: {system}",
            f"Python: {platform.python_version()}",
            f"Free space: {free // 1024**3} GB",
            f"Database: {size // 1024} KB",
            f"Proxy: {'yes' if proxy else 'no'}",
            f"Events: {count}, failed listeners: {failed}",
        ]
    )
    return Diagnostics(
        version=__version__,
        platform=system,
        python=platform.python_version(),
        home=str(home),
        free_bytes=free,
        database_bytes=size,
        proxy=proxy,
        event_count=count,
        failed_events=failed,
        report=report,
    )


@system_module.command("network.check")
def check_network(command: CheckNetwork, ctx: Context) -> NetworkChecks:
    checks = []
    targets = [
        ("OpenAI sign-in", ctx.config.chatgpt.issuer),
        ("ChatGPT", ctx.config.chatgpt.base_url),
    ]
    with httpx.Client(timeout=ctx.config.network_check_timeout_seconds) as client:
        for name, url in targets:
            host = urlparse(url).netloc
            try:
                # Any answer means the path is open; a login page's error status doesn't matter.
                response = client.get(url)
                checks.append(
                    NetworkCheck(
                        name=name, host=host, ok=True, detail=f"HTTP {response.status_code}"
                    )
                )
            except httpx.ProxyError:
                checks.append(
                    NetworkCheck(
                        name=name, host=host, ok=False, detail="The proxy refused the connection."
                    )
                )
            except httpx.HTTPError:
                checks.append(
                    NetworkCheck(name=name, host=host, ok=False, detail="Couldn't connect.")
                )
    return NetworkChecks(checks=checks)
