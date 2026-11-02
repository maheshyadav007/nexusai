"""A stand-in for OpenAI's sign-in and ChatGPT servers, so no test touches a real account."""

import asyncio
import base64
import json
import os
import time
import uuid
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

        last = body["input"][-1]
        said = "".join(p.get("text", "") for p in last.get("content", []) if isinstance(p, dict))

        async def stream() -> Any:
            def event(kind: str, **fields: Any) -> str:
                return f"data: {json.dumps({'type': kind, **fields})}\n\n"

            if "call record_triage" in said:
                urgent = "urgent" in said.lower()
                reply = {
                    "category": "Action",
                    "importance": "high" if urgent else "normal",
                    "status": "waiting_on_you",
                    "summary": "Someone needs a reply.",
                    "reason": "It asks you a direct question.",
                    "facts": ["Due soon"],
                    "suggested_action": "Reply today",
                    "deadlines": [],
                    "tasks": [{"title": "Reply to this mail", "due": None}]
                    if "task" in said.lower()
                    else [],
                    "reminders": [],
                    "draft": "Thanks, I'll look at this." if "draft" in said.lower() else None,
                    "memory": "Remember this person." if "remember" in said.lower() else None,
                    "question": "Is this urgent for you?" if "question" in said.lower() else None,
                }
                yield event(
                    "response.output_item.done",
                    item={
                        "type": "function_call",
                        "call_id": f"triage-{uuid.uuid4().hex}",
                        "name": "record_triage",
                        "arguments": json.dumps(reply),
                    },
                )
            elif "Summarize a mail conversation" in body.get("instructions", ""):
                yield event("response.output_text.delta", delta="They want the numbers by Friday.")
            elif last.get("type") == "function_call_output":
                yield event("response.output_text.delta", delta=f"Tool said: {last['output'][:60]}")
            elif "remind me" in said:
                yield event(
                    "response.output_item.done",
                    item={
                        "type": "function_call",
                        "call_id": "reminder-call",
                        "name": "create_reminders",
                        "arguments": json.dumps(
                            {
                                "reminders": [
                                    {"title": "Call the vendor", "when": "2031-05-01T09:00"}
                                ]
                            }
                        ),
                    },
                )
            elif "add three tasks" in said:
                for title in ("First task", "Second task", "Third task"):
                    yield event(
                        "response.output_item.done",
                        item={
                            "type": "function_call",
                            "call_id": f"task-{uuid.uuid4().hex}",
                            "name": "create_tasks",
                            "arguments": json.dumps({"tasks": [{"title": title}]}),
                        },
                    )
            elif "ask me something" in said:
                yield event(
                    "response.output_item.done",
                    item={
                        "type": "function_call",
                        "call_id": f"ask-{uuid.uuid4().hex}",
                        "name": "ask_user",
                        "arguments": json.dumps(
                            {
                                "question": "Which day works?",
                                "options": ["Monday", "Tuesday"],
                                "multiple": "several" in said,
                            }
                        ),
                    },
                )
            elif "send an email" in said:
                yield event(
                    "response.output_item.done",
                    item={
                        "type": "function_call",
                        "call_id": f"send-{uuid.uuid4().hex}",
                        "name": "send_mail",
                        "arguments": json.dumps(
                            {
                                "to": ["sam@example.com"],
                                "subject": "Numbers",
                                "body": "Here they are.",
                            }
                        ),
                    },
                )
            elif "offer next steps" in said:
                yield event("response.output_text.delta", delta="Here is the **answer**.\n<follow")
                yield event(
                    "response.output_text.delta", delta='ups>["Tell me more", "Do it"]</followups>'
                )
            elif "run a command" in said:
                arguments = json.dumps(
                    {"command": "echo from-the-agent", "why": "Prove commands work"}
                )
                item = {
                    "type": "function_call",
                    "call_id": f"call-{uuid.uuid4().hex[:8]}",
                    "name": "run_command",
                    "arguments": arguments,
                }
                yield event("response.output_item.done", item=item)
            elif "slow" in said:
                for number in range(30):
                    yield event("response.output_text.delta", delta=f"word{number} ")
                    await asyncio.sleep(0.2)
            else:
                for piece in ("Hello ", "from ", body["model"]):
                    yield event("response.output_text.delta", delta=piece)
            yield event(
                "response.completed", response={"usage": {"input_tokens": 11, "output_tokens": 3}}
            )

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/__sent")
    async def sent() -> list[dict[str, Any]]:
        return state["bodies"]

    return app


if __name__ == "__main__":
    uvicorn.run(
        create_fake(), host="127.0.0.1", port=int(os.environ.get("FAKE_CHATGPT_PORT", 8766))
    )
