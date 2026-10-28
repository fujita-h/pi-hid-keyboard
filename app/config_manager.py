"""Strict JSON configuration, immutable snapshots, atomic on-disk replacement."""

import copy
import json
import os
import re
import tempfile
import threading
from pathlib import Path

from app.macro_executor import MacroCompiler, ValidationError

MAX_CONFIG_BYTES = 256 * 1024
SAMPLE_PATH = Path(__file__).resolve().parent.parent / "data" / "macros.example.json"


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValidationError(f"Duplicate JSON field: {key}")
        obj[key] = value
    return obj


class ConfigManager:
    def __init__(self, path, compiler=None):
        self.path = Path(path)
        self.compiler = compiler or MacroCompiler()
        self._lock = threading.RLock()
        if self.path.exists():
            self._raw = self.path.read_bytes()
            self._config = self.parse(self._raw)
        else:
            self.import_bytes(SAMPLE_PATH.read_bytes())

    def parse(self, raw):
        if len(raw) > MAX_CONFIG_BYTES:
            raise ValidationError("JSON file exceeds 256 KiB")
        try:
            config = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object)
        except (UnicodeError, ValueError, RecursionError) as exc:
            raise ValidationError(f"Invalid UTF-8 JSON: {exc}") from exc
        if (
            not isinstance(config, dict)
            or set(config) != {"version", "macros"}
            or type(config["version"]) is not int
            or config["version"] != 1
        ):
            raise ValidationError("Configuration requires version: 1 and macros")
        macros = config["macros"]
        if not isinstance(macros, list) or len(macros) > 100:
            raise ValidationError("macros must be an array with at most 100 entries")
        ids = set()
        for index, macro in enumerate(macros):
            try:
                if not isinstance(macro, dict) or set(macro) != {"id", "label", "steps"}:
                    raise ValidationError("Macro requires only id, label and steps")
                macro_id = macro["id"]
                if not isinstance(macro_id, str) or not re.fullmatch(
                    r"[A-Za-z0-9_-]{1,64}", macro_id
                ):
                    raise ValidationError("id must be 1–64 ASCII letters, digits, _ or -")
                if macro_id in ids:
                    raise ValidationError("Duplicate macro id")
                ids.add(macro_id)
                label = macro["label"]
                if (
                    not isinstance(label, str)
                    or not label.strip()
                    or len(label) > 100
                    or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in label)
                ):
                    raise ValidationError("label must contain 1–100 displayable characters")
                self.compiler.compile(macro["steps"])
            except ValidationError as exc:
                raise ValidationError(f"macros[{index}]: {exc}") from exc
        return config

    def import_bytes(self, raw):
        config = self.parse(raw)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix=".macros-", dir=self.path.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(name, self.path)
                # Publish only after replacement succeeds. Preserve the uploaded bytes.
                self._config = config
                self._raw = bytes(raw)
                directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                if os.path.exists(name):
                    os.unlink(name)

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self._config)

    def export_bytes(self):
        with self._lock:
            return self._raw

    def get_macro(self, macro_id):
        with self._lock:
            return next(
                (copy.deepcopy(m) for m in self._config["macros"] if m["id"] == macro_id), None
            )
