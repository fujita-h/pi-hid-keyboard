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
# The API exposes only these tabs, so the browser needs no separate limit.
MAX_VISIBLE_TABS = 10
MAX_MACROS_PER_TAB = 100
SAMPLE_PATH = Path(__file__).resolve().parent.parent / "data" / "macros.example.json"


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValidationError(f"Duplicate JSON field: {key}")
        obj[key] = value
    return obj


def _validate_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise ValidationError("id must be 1–64 ASCII letters, digits, _ or -")


def _validate_label(value):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 100
        or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value)
    ):
        raise ValidationError("label must contain 1–100 displayable characters")


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
            or set(config) != {"version", "tabs"}
            or type(config["version"]) is not int
            or config["version"] != 1
        ):
            raise ValidationError("Configuration requires version: 1 and tabs")
        if not isinstance(config["tabs"], list):
            raise ValidationError("tabs must be an array")
        # Keep the original bytes for export, including ignored tabs. Only the
        # visible prefix is validated, listed, and available for execution.
        config["tabs"] = config["tabs"][:MAX_VISIBLE_TABS]
        tab_ids = set()
        macro_ids = set()
        for index, tab in enumerate(config["tabs"]):
            try:
                if not isinstance(tab, dict) or set(tab) != {"id", "label", "macros"}:
                    raise ValidationError("Tab requires only id, label and macros")
                _validate_id(tab["id"])
                _validate_label(tab["label"])
                if tab["id"] in tab_ids:
                    raise ValidationError("Duplicate tab id")
                tab_ids.add(tab["id"])
                self._validate_macros(tab["macros"], macro_ids)
            except ValidationError as exc:
                raise ValidationError(f"tabs[{index}]: {exc}") from exc
        return config

    def _validate_macros(self, macros, ids):
        if not isinstance(macros, list) or len(macros) > MAX_MACROS_PER_TAB:
            raise ValidationError(
                f"macros must be an array with at most {MAX_MACROS_PER_TAB} entries"
            )
        for index, macro in enumerate(macros):
            try:
                if not isinstance(macro, dict) or set(macro) != {"id", "label", "steps"}:
                    raise ValidationError("Macro requires only id, label and steps")
                macro_id = macro["id"]
                _validate_id(macro_id)
                if macro_id in ids:
                    raise ValidationError("Duplicate macro id")
                ids.add(macro_id)
                _validate_label(macro["label"])
                self.compiler.compile(macro["steps"])
            except ValidationError as exc:
                raise ValidationError(f"macros[{index}]: {exc}") from exc

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
                (
                    copy.deepcopy(m)
                    for tab in self._config["tabs"]
                    for m in tab["macros"]
                    if m["id"] == macro_id
                ),
                None,
            )
