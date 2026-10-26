"""Bounded offline IO for untrusted evidence under an explicitly trusted root.

POSIX descriptor-relative operations are required. No network or source writes.
Errors expose fixed codes, never OS exception text or artifact contents.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


class EvidenceError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def strict_json(raw: bytes):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise EvidenceError("duplicate_json_key")
            result[key] = value
        return result

    def finite(text):
        value = float(text)
        if not math.isfinite(value):
            raise EvidenceError("nonfinite_json")
        return value

    def constant(_):
        raise EvidenceError("nonfinite_json")

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                          parse_float=finite, parse_constant=constant)
    except EvidenceError:
        raise
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        raise EvidenceError("malformed_json") from None


class _NoDeclarations(ET.TreeBuilder):
    def __init__(self):
        super().__init__()
        self.nodes = 0
        self.depth = 0

    def start(self, tag, attrs):
        self.nodes += 1
        self.depth += 1
        if self.nodes > 100_000:
            raise EvidenceError("xml_node_limit")
        if self.depth > 128:
            raise EvidenceError("xml_depth_limit")
        return super().start(tag, attrs)

    def end(self, tag):
        self.depth -= 1
        return super().end(tag)

    def doctype(self, name, pubid, system):
        raise EvidenceError("forbidden_xml_declaration")


def safe_xml(raw: bytes) -> tuple[str, ET.Element]:
    try:
        # Existing collectors write decoded text as UTF-8. Other encodings are
        # unsupported; decoding first also blocks UTF-16/NUL declaration tricks.
        text = raw.decode("utf-8")
        if "\x00" in text:
            raise EvidenceError("unsupported_xml_encoding")
        declaration = re.match(r"\s*<\?xml\b[^?]*encoding\s*=\s*['\"]([^'\"]+)", text, re.IGNORECASE)
        if declaration and declaration[1].lower() not in ("utf-8", "utf8", "us-ascii"):
            raise EvidenceError("unsupported_xml_encoding")
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise EvidenceError("forbidden_xml_declaration")
        parser = ET.XMLParser(target=_NoDeclarations())
        root = ET.fromstring(text, parser=parser)
        return text, root
    except EvidenceError:
        raise
    except (UnicodeError, ET.ParseError, ValueError, RecursionError):
        raise EvidenceError("malformed_xml") from None


def parts(relative: str) -> tuple[str, ...]:
    if (not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative
            or any(ord(c) < 32 or ord(c) == 127 for c in relative)):
        raise EvidenceError("unsafe_path")
    result = tuple(relative.split("/"))
    if any(p in ("", ".", "..") for p in result):
        raise EvidenceError("unsafe_path")
    return result


def _flags(directory=False):
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise EvidenceError("unsupported_platform")
    return os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | (os.O_DIRECTORY if directory else 0)


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _directory(path: Path) -> int:
    # Walk every absolute component rather than only protecting the final one.
    absolute = path.absolute()
    components = absolute.parts[1:]
    if any(p in (".", "..") for p in components):
        raise EvidenceError("unsafe_path")
    fd = os.open("/", _flags(True))
    try:
        for component in components:
            next_fd = os.open(component, _flags(True), dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


@dataclass(frozen=True)
class Snapshot:
    path: str
    data: bytes
    byte_sha256: str
    stamp: tuple


class EvidenceRoot:
    def __init__(self, path: Path | str, *, max_bytes=8 * 1024 * 1024,
                 max_total_bytes=64 * 1024 * 1024, max_files=4096, max_depth=16):
        if any(type(v) is not int or v < 1 for v in (max_bytes, max_total_bytes, max_files, max_depth)):
            raise EvidenceError("invalid_limits")
        self.path = Path(path).absolute()
        self.max_bytes, self.max_total_bytes = max_bytes, max_total_bytes
        self.max_files, self.max_depth = max_files, max_depth
        self.total = 0
        self.fd = -1

    def __enter__(self):
        try:
            self.fd = _directory(self.path)
            return self
        except OSError:
            raise EvidenceError("unsafe_or_unreadable_root") from None

    def __exit__(self, *exc):
        if self.fd != -1:
            os.close(self.fd)
            self.fd = -1

    def _open(self, relative: str) -> int:
        segments = parts(relative)
        fd = os.dup(self.fd)
        try:
            for segment in segments[:-1]:
                next_fd = os.open(segment, _flags(True), dir_fd=fd)
                os.close(fd)
                fd = next_fd
            return os.open(segments[-1], _flags(), dir_fd=fd)
        finally:
            os.close(fd)

    def read(self, relative: str, *, recheck=False) -> Snapshot:
        try:
            fd = self._open(relative)
            try:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                    raise EvidenceError("unsafe_file_type")
                if before.st_size > self.max_bytes:
                    raise EvidenceError("oversized")
                if not recheck:
                    self.total += before.st_size
                    if self.total > self.max_total_bytes:
                        raise EvidenceError("total_size_limit")
                # Never rely on st_size alone: a file can grow after fstat.
                with os.fdopen(os.dup(fd), "rb") as stream:
                    raw = stream.read(self.max_bytes + 1)
                if len(raw) > self.max_bytes:
                    raise EvidenceError("oversized")
                after = os.fstat(fd)
                if _stamp(before) != _stamp(after) or len(raw) != before.st_size:
                    raise EvidenceError("changed_during_read")
                probe = self._open(relative)
                try:
                    if _stamp(os.fstat(probe)) != _stamp(after):
                        raise EvidenceError("changed_during_read")
                finally:
                    os.close(probe)
                root_probe = _directory(self.path)
                try:
                    if os.fstat(root_probe).st_ino != os.fstat(self.fd).st_ino or os.fstat(root_probe).st_dev != os.fstat(self.fd).st_dev:
                        raise EvidenceError("changed_root")
                finally:
                    os.close(root_probe)
                return Snapshot(relative, raw, hashlib.sha256(raw).hexdigest(), _stamp(after))
            finally:
                os.close(fd)
        except FileNotFoundError:
            raise EvidenceError("missing_file") from None
        except PermissionError:
            raise EvidenceError("unreadable_file") from None
        except OSError:
            raise EvidenceError("unsafe_or_unreadable_path") from None

    def discover(self) -> tuple[str, ...]:
        found = []
        count = 0

        def visit(fd, prefix, depth):
            nonlocal count
            if depth > self.max_depth:
                raise EvidenceError("directory_depth_limit")
            with os.scandir(fd) as iterator:
                names = []
                for entry in iterator:
                    count += 1
                    if count > self.max_files:
                        raise EvidenceError("file_count_limit")
                    names.append(entry.name)
            for name in sorted(names):
                relative = prefix + name
                parts(relative)
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(name, _flags(True), dir_fd=fd)
                    try:
                        visit(child, relative + "/", depth + 1)
                    finally:
                        os.close(child)
                else:
                    found.append(relative)

        try:
            visit(self.fd, "", 0)
        except OSError:
            raise EvidenceError("directory_changed_or_unreadable") from None
        return tuple(sorted(found))


def write_report(destination: str, text: str, evidence_root: str) -> None:
    """Exclusive create outside evidence; no directory creation or overwrites."""
    target = Path(destination).absolute()
    root = Path(evidence_root).absolute()
    if target == root or root in target.parents:
        raise EvidenceError("output_inside_evidence")
    parts(target.name)
    try:
        fd = _directory(target.parent)
        try:
            output = os.open(target.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=fd)
            with os.fdopen(output, "w", encoding="utf-8") as stream:
                stream.write(text + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(fd)
    except OSError:
        raise EvidenceError("unsafe_or_unwritable_output") from None
