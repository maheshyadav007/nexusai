"""The local models NexusAI knows, pinned to exact files so what runs is what was checked."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DIMENSIONS = 384
QUANTIZATION = "int8"
# Raised when the way vectors are made changes, so what's there shows as out of date.
PIPELINE_VERSION = 1


@dataclass(frozen=True)
class ModelFile:
    name: str
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class CatalogModel:
    id: str
    label: str
    description: str
    repo: str
    revision: str
    files: tuple[ModelFile, ...]
    # Some models were trained to tell a question from the text that answers it.
    query_prefix: str = ""
    passage_prefix: str = ""
    # Below this it's only loosely related, and showing it would hide what did match. Each model
    # has its own scale. Measured on 16 labelled pairs: e5 keeps 7 of 8 related and 0 of 8 unrelated
    # at 0.80, and MiniLM keeps the 5 English related and 0 unrelated at 0.25.
    min_score: float = 0.0
    # How far above this query's typical score a match has to be, when scores bunch together.
    noise_margin: float = 0.0

    @property
    def size(self) -> int:
        return sum(item.size for item in self.files)


MODELS = (
    CatalogModel(
        id="multilingual-e5-small",
        label="Many languages",
        description="English, Korean, Hindi and over 100 more. Best results.",
        repo="Xenova/multilingual-e5-small",
        revision="761b726dd34fb83930e26aab4e9ac3899aa1fa78",
        files=(
            ModelFile(
                "model.onnx",
                "onnx/model_quantized.onnx",
                118308185,
                "f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193",
            ),
            ModelFile(
                "tokenizer.json",
                "tokenizer.json",
                17082730,
                "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39",
            ),
        ),
        query_prefix="query: ",
        passage_prefix="passage: ",
        min_score=0.80,
        noise_margin=0.02,
    ),
    CatalogModel(
        id="all-minilm-l6-v2",
        label="English only, smaller",
        description="A much smaller download, for mail that's all in English.",
        repo="Xenova/all-MiniLM-L6-v2",
        revision="751bff37182d3f1213fa05d7196b954e230abad9",
        files=(
            ModelFile(
                "model.onnx",
                "onnx/model_quantized.onnx",
                22972370,
                "afdb6f1a0e45b715d0bb9b11772f032c399babd23bfc31fed1c170afc848bdb1",
            ),
            ModelFile(
                "tokenizer.json",
                "tokenizer.json",
                711661,
                "da0e79933b9ed51798a3ae27893d3c5fa4a201126cef75586296df9b4d2c62a0",
            ),
        ),
        min_score=0.25,
    ),
)
BY_ID = {model.id: model for model in MODELS}
DEFAULT = MODELS[0].id


def build_settings(model: CatalogModel, **chunking: int) -> dict[str, Any]:
    """Everything that decides what a vector means. Different settings need different vectors."""
    return {
        "model": model.id,
        "label": model.label,
        "repo": model.repo,
        "revision": model.revision,
        "files": {item.name: item.sha256 for item in model.files},
        "dimensions": DIMENSIONS,
        "quantization": QUANTIZATION,
        "query_prefix": model.query_prefix,
        "passage_prefix": model.passage_prefix,
        "pipeline": PIPELINE_VERSION,
        **chunking,
    }


def fingerprint_of(settings: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:16]


def folder(home: Path, model: CatalogModel) -> Path:
    return home / "system" / "models" / model.id


def url(model: CatalogModel, item: ModelFile, source: str) -> str:
    return f"{source.rstrip('/')}/{model.repo}/resolve/{model.revision}/{item.path}"
