"""Bounded-memory writer for the unchanged P032 canonical JSON bytes."""

import hashlib
import json
import math
import tempfile
import weakref
from dataclasses import fields, is_dataclass
from functools import lru_cache

from .codec import require


def file_sha256(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class FrozenEventArray:
    """Exact canonical array cache for a single writer's immutable event prefix.

    The temporary spool is not evidence or a replacement for the saved file.
    Every copy verifies all cached bytes; the surrounding atomic writer commits
    only after that check. Prefix truncation or replacement is always refused.
    """

    def __init__(self, directory):
        self.stream = tempfile.TemporaryFile(mode="w+b", dir=directory)
        weakref.finalize(self, self.stream.close)
        self.events = ()
        self.length = 0
        self.hasher = hashlib.sha256()

    def append(self, events):
        require(
            len(events) >= len(self.events) and all(a is b for a, b in zip(self.events, events)),
            "SAVE_EVENT_PREFIX_MUTATED",
        )
        additions = tuple(events[len(self.events) :])
        require(
            all(is_dataclass(e) and e.__dataclass_params__.frozen for e in additions),
            "SAVE_EVENTS_NOT_FROZEN",
        )
        checksum = self.hasher.copy()
        target = self.stream
        target.seek(self.length)

        class Writer:
            def write(self, data):
                target.write(data)
                checksum.update(data)

        writer = Writer()
        try:
            for index, event in enumerate(additions):
                if self.events or index:
                    writer.write(b",")
                write_canonical(writer, event)
        except BaseException:
            target.seek(self.length)
            target.truncate()
            raise
        self.length = target.tell()
        self.hasher = checksum
        self.events += additions

    def pieces(self):
        self.stream.seek(0)
        checksum = hashlib.sha256()
        remaining = self.length
        yield b"["
        while remaining:
            data = self.stream.read(min(65536, remaining))
            require(bool(data), "SAVE_EVENT_CACHE_TRUNCATED")
            remaining -= len(data)
            checksum.update(data)
            yield data
        require(not self.stream.read(1), "SAVE_EVENT_CACHE_EXTENDED")
        require(checksum.digest() == self.hasher.digest(), "SAVE_EVENT_CACHE_CHANGED")
        yield b"]"


@lru_cache(maxsize=4096, typed=True)
def _small_atom(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
        "utf-8"
    )


def _atom(value):
    kind = type(value)
    if kind is float:
        require(math.isfinite(value), "NONFINITE_JSON")
        value = int(value) if value.is_integer() else value
    else:
        require(value is None or kind in (str, int, bool), "JSON_TYPE")
    if type(value) is str and len(value) > 256:
        return json.dumps(value, ensure_ascii=False).encode("utf-8")
    return _small_atom(value)


@lru_cache(maxsize=256)
def _field_names(kind):
    return tuple(sorted(f.name for f in fields(kind)))


def _pieces(value):
    kind = type(value)
    if kind is FrozenEventArray:
        yield from value.pieces()
    elif kind is dict or is_dataclass(value) and not isinstance(value, type):
        if kind is dict:
            require(all(type(k) is str for k in value), "JSON_KEY")
            keys = sorted(value)
            get = value.__getitem__
        else:
            keys = _field_names(kind)

            def get(key):
                return getattr(value, key)

        yield b"{"
        for index, key in enumerate(keys):
            if index:
                yield b","
            yield _atom(key)
            yield b":"
            yield from _pieces(get(key))
        yield b"}"
    elif kind in (list, tuple):
        yield b"["
        for index, item in enumerate(value):
            if index:
                yield b","
            yield from _pieces(item)
        yield b"]"
    else:
        yield _atom(value)


def write_canonical(stream, value, *, chunk_bytes=65536):
    """Write canonical bytes, accepting dataclasses as their as_data view.

    No normalized tree or complete encoded document is retained. The caller
    owns atomic replacement, flush and fsync; partial writes never imply commit.
    """
    require(type(chunk_bytes) is int and chunk_bytes > 0, "CHUNK_SIZE")
    buffer = bytearray()
    for piece in _pieces(value):
        buffer.extend(piece)
        if len(buffer) >= chunk_bytes:
            stream.write(buffer)
            buffer.clear()
    if buffer:
        stream.write(buffer)
