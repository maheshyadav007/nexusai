"""A stand-in for OpenAI's sign-in and ChatGPT servers, so no test touches a real account."""

import base64
import json
import os
import time
from typing import Any
from urllib.parse import parse_qs

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

ACCOUNT = "acct-test"


def token(name: str, *, expires_in: int = 3600) -> str:
    claims = {
        "exp": int(time.time()) + expires_in,
        "name": name,
        "https://api.openai.com/profile": {"email": "tester@example.com"},
        "https://api.openai.com/auth": {"chatgpt_account_id": ACCOUNT, "chatgpt_plan_type": "plus"},
    }
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"h.{body}.s"


def create_fake() -> FastAPI:
    app = FastAPI()
    state: dict[str, Any] = {
        "polls_until_done": 1,
        "polls": 0,
        "refresh_tokens": ["refresh-1"],
        "access": token("access-1"),
        "revoked": False,
        "reject_next_request": False,
        "headers": [],
        "bodies": [],
    }
    app.state.fake = state

    @app.post("/api/accounts/deviceauth/usercode")
    async def usercode() -> dict[str, Any]:
        return {"device_auth_id": "device-1", "user_code": "WXYZ-1234", "interval": "0"}

    @app.post("/api/accounts/deviceauth/token")
    async def poll() -> Response:
        state["polls"] += 1
        if state["polls"] <= state["polls_until_done"]:
            return Response(status_code=403)
        return JSONResponse({"authorization_code": "code-1", "code_verifier": "verifier-1"})

    @app.post("/oauth/token")
    async def oauth(request: Request) -> Response:
        form = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}
        if form["grant_type"] == "authorization_code":
            refresh = state["refresh_tokens"][-1]
            return JSONResponse({"access_token": state["access"], "refresh_token": refresh})
        if state["revoked"] or form["refresh_token"] != state["refresh_tokens"][-1]:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        state["refresh_tokens"].append(f"refresh-{len(state['refresh_tokens']) + 1}")
        state["access"] = token(f"access-{len(state['refresh_tokens'])}")
        return JSONResponse(
            {"access_token": state["access"], "refresh_token": state["refresh_tokens"][-1]}
        )

    def refused(request: Request) -> Response | None:
        state["headers"].append(dict(request.headers))
        if state["reject_next_request"]:
            state["reject_next_request"] = False
            return Response(status_code=401)
        if request.headers.get("authorization") != f"Bearer {state['access']}":
            return Response(status_code=401)
        return None

    @app.get("/codex/models")
    async def models(request: Request) -> Response:
        if failure := refused(request):
            return failure
        # As the real server does: an empty list, not an error, without the account header.
        if request.headers.get("chatgpt-account-id") != ACCOUNT:
            return JSONResponse({"models": []})
        return JSONResponse(
            {
                "models": [
                    {"slug": "gpt-slow", "display_name": "GPT Slow", "priority": 2},
                    {"slug": "gpt-secret", "display_name": "Hidden", "visibility": "hide"},
                    {"slug": "gpt-best", "display_name": "GPT Best", "priority": 1},
                ]
            }
        )

    @app.post("/codex/responses")
    async def responses(request: Request) -> Response:
        if failure := refused(request):
            return failure
        body = await request.json()
        state["bodies"].append(body)

        async def stream() -> Any:
            for piece in ("Hello ", "from ", body["model"]):
                event = {"type": "response.output_text.delta", "delta": piece}
                yield f"data: {json.dumps(event)}\n\n"
            yield f"data: {json.dumps({'type': 'response.completed'})}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    return app


if __name__ == "__main__":
    uvicorn.run(
        create_fake(), host="127.0.0.1", port=int(os.environ.get("FAKE_CHATGPT_PORT", 8766))
    )
