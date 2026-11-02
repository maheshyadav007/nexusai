from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DocumentSource = Literal["upload", "email", "home"]
ReaderKind = Literal["pdf", "image", "markdown", "code", "table", "html", "document", "other"]


FileType = Literal["pdf", "word", "sheet", "slides", "image", "other"]


class ListDocuments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_type: FileType | None = None
    # Who it came from, for attachments.
    sender: str | None = Field(default=None, max_length=320)
    date_from: str | None = Field(default=None, max_length=32)
    date_to: str | None = Field(default=None, max_length=32)
    source: DocumentSource | None = None
    folder: str | None = Field(default=None, max_length=200)
    tag: str | None = Field(default=None, max_length=64)
    query: str = Field(default="", max_length=500)
    limit: int = Field(default=200, ge=1, le=1000)


class DocumentRow(BaseModel):
    sender: str | None = None
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
    # The page, slide or sheet a search by meaning found it on.
    place: str | None = None


class DocumentLibrary(BaseModel):
    documents: list[DocumentRow]
    folders: list[str]
    tags: list[str]


class GetDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(max_length=64)


class ListHomeFolder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Relative to Home. Empty is the top, which shows only the folders that can be looked at.
    path: str = Field(default="", max_length=4096)


class HomeEntry(BaseModel):
    name: str
    # What to show, when the name on disk means nothing to a person.
    label: str
    path: str
    is_folder: bool
    size: int = 0
    modified: str | None = None


class HomeFolder(BaseModel):
    path: str
    entries: list[HomeEntry]


class ReadDocument(BaseModel):
    """A document from the library by its key, or any file under Home by its path."""

    model_config = ConfigDict(extra="forbid")

    key: str | None = Field(default=None, max_length=64)
    path: str | None = Field(default=None, max_length=4096)


class DocumentReader(BaseModel):
    name: str
    kind: ReaderKind
    text: str
    status: str = "ready"
    status_reason: str | None = None
    url: str
    key: str | None = None
    # Cleaned of scripts and anything that would load from outside.
    html: str | None = None


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
