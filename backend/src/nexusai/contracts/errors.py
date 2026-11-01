from pydantic import BaseModel


class ApiError(BaseModel):
    code: str
    message: str
    trace_id: str | None = None
