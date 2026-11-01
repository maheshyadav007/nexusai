"""Turns text into vectors on this computer. Nothing here touches the network."""

import threading
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

from nexusai.modules.semantic.catalog import CatalogModel, folder

MAX_TOKENS = 256
# Leaves the computer usable while mail is indexed in the background.
THREADS = 2


class Embedder(Protocol):
    def embed(self, texts: list[str], *, query: bool) -> NDArray[np.float32]: ...


class OnnxEmbedder:
    def __init__(self, home: Path, model: CatalogModel) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        base = folder(home, model)
        options = ort.SessionOptions()
        options.intra_op_num_threads = THREADS
        options.inter_op_num_threads = 1
        self.model = model
        self.session: Any = ort.InferenceSession(
            str(base / "model.onnx"), options, providers=ort.get_available_providers()[-1:]
        )
        self.inputs = {item.name for item in self.session.get_inputs()}
        self.tokenizer: Any = Tokenizer.from_file(str(base / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=MAX_TOKENS)
        self.tokenizer.enable_padding()
        self.lock = threading.Lock()

    def embed(self, texts: list[str], *, query: bool) -> NDArray[np.float32]:
        prefix = self.model.query_prefix if query else self.model.passage_prefix
        with self.lock:
            encoded = self.tokenizer.encode_batch([prefix + text for text in texts])
            ids = np.array([item.ids for item in encoded], dtype=np.int64)
            mask = np.array([item.attention_mask for item in encoded], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            output = self.session.run(None, feed)[0]
        weights = mask[..., None]
        pooled = (output * weights).sum(axis=1) / weights.sum(axis=1)
        return np.asarray(pooled / np.linalg.norm(pooled, axis=1, keepdims=True), dtype=np.float32)
