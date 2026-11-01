from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DocumentSource = Literal["upload", "email"]


class ListDocuments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: DocumentSource | None = None
    folder: str | None = Field(default=None, max_length=200)
    tag: str | None = Field(default=None, max_length=64)
    query: str = Field(default="", max_length=500)
    limit: int = Field(default=200, ge=1, le=1000)


class DocumentRow(BaseModel):
    key: str
    name: str
    content_type: str
    size: int
    date: str
    source: DocumentSource
    folder: str | None
    tags: list[str]
    thread_id: int | None = None
    risky: bool = False
    # ready, pending, no_text, encrypted, unsupported, too_large, image, empty or failed.
    status: str = "ready"
    status_reason: str | None = None
    # Added again with the same content, so this is the one already here.
    duplicate: bool = False


class DocumentLibrary(BaseModel):
    documents: list[DocumentRow]
    folders: list[str]
    tags: list[str]


class GetDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(max_length=64)


class DocumentPreview(BaseModel):
    document: DocumentRow
    text: str


class UpdateDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(max_length=64)
    folder: str | None = Field(default=None, max_length=200)
    tags: list[str] = Field(default_factory=list, max_length=32)


class RemoveDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(max_length=64)


class SaveFolders(BaseModel):
    """The person's folders, in their chosen order."""

    model_config = ConfigDict(extra="forbid")

    folders: list[str] = Field(max_length=500)


class ReadDocumentAgain(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(max_length=64)


class DocumentDone(BaseModel):
    ok: bool = True
