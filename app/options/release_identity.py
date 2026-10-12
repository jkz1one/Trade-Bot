"""Bounded installed-file evidence, never release approval or process attestation."""

import base64
import csv
import hashlib
import importlib.metadata
import io
import json
import os
import platform
import stat
from datetime import datetime
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field, model_validator

import app
from app.domain.models import utc_now
from app.options.models import OptionRecord

PACKAGE = "autonomous-compounding-trader"
MAX_FILES = 512
MAX_BYTES = 16 * 1024 * 1024


class InstalledRelease(OptionRecord):
    version: Literal["options-installed-release-v1"] = "options-installed-release-v1"
    status: Literal["VERIFIED_FILES", "UNAVAILABLE", "MISMATCH"]
    observed_at: datetime
    package: Literal["autonomous-compounding-trader"] = PACKAGE
    package_version: str | None = Field(default=None, min_length=1, max_length=64)
    python_version: str = Field(min_length=1, max_length=32)
    application_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    wheel_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    file_count: int = Field(default=0, ge=0, le=MAX_FILES, strict=True)
    reason: str | None = Field(default=None, max_length=128, pattern=r"^[A-Z_]+$")
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def coherent(self):
        if self.status == "VERIFIED_FILES":
            if (
                self.application_sha256 is None
                or self.package_version is None
                or self.file_count == 0
                or self.reason is not None
            ):
                raise ValueError("Verified installed files require complete bounded identity")
        elif (
            self.application_sha256 is not None
            or self.wheel_sha256 is not None
            or self.file_count
            or self.reason is None
        ):
            raise ValueError("Unavailable identity cannot retain a verified digest")
        return self


def _read(path, maximum):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
            raise ValueError("Bounded regular package file required")
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
        if len(raw) > maximum or (before.st_size, before.st_mtime_ns) != (
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ValueError("Installed file changed during inspection")
        return raw


def _inspect(distribution, module_file):
    root = Path(distribution.locate_file(""))
    package_root = root / "app"
    if (
        package_root.is_symlink()
        or Path(module_file).resolve() != (package_root / "__init__.py").resolve()
    ):
        return "UNAVAILABLE", "IMPORT_OUTSIDE_INSTALLED_PACKAGE", {}
    # PathDistribution is the local wheel-installation backend. Read its metadata
    # directly with limits instead of unbounded Distribution.files/read_text.
    if not isinstance(distribution, importlib.metadata.PathDistribution):
        return "UNAVAILABLE", "UNSUPPORTED_INSTALLATION_BACKEND", {}
    metadata_path = Path(distribution._path)
    if (
        metadata_path.is_symlink()
        or metadata_path.parent.resolve() != root.resolve()
        or not metadata_path.name.endswith(".dist-info")
    ):
        return "UNAVAILABLE", "INSTALLATION_RECORD_UNAVAILABLE", {}
    headers = BytesParser().parsebytes(_read(metadata_path / "METADATA", 65536))
    if headers.get_all("Name") != [PACKAGE] or len(headers.get_all("Version", [])) != 1:
        raise ValueError("Package metadata identity mismatch")
    raw_record = _read(metadata_path / "RECORD", 256 * 1024).decode("utf-8")
    entries = {}
    for number, row in enumerate(csv.reader(io.StringIO(raw_record)), 1):
        if number > MAX_FILES * 3 or len(row) != 3:
            raise ValueError("Invalid bounded installation record")
        name, digest, size = row
        if name.startswith("app/"):
            parts = PurePosixPath(name).parts
            if "__pycache__" in parts:
                continue
            if ".." in parts or name in entries or len(entries) >= MAX_FILES:
                raise ValueError("Invalid application record")
            entries[name] = (digest, size)
    origin = metadata_path / "direct_url.json"
    metadata = json.loads(_read(origin, 16384)) if origin.exists() else {}
    if not isinstance(metadata, dict):
        raise TypeError("Invalid installation metadata")
    if metadata.get("dir_info", {}).get("editable") is True:
        return "UNAVAILABLE", "EDITABLE_INSTALLATION", {}
    if "app/__init__.py" not in entries:
        return "UNAVAILABLE", "INSTALLATION_RECORD_UNAVAILABLE", {}
    actual = set()
    for directories, (parent, dirs, names) in enumerate(
        os.walk(package_root, followlinks=False), 1
    ):
        if directories > MAX_FILES:
            raise ValueError("Application directory capacity exceeded")
        if "__pycache__" in dirs:
            dirs.remove("__pycache__")
        if any((Path(parent) / d).is_symlink() for d in dirs):
            raise ValueError("Symlinked application directory")
        for name in names:
            actual.add(str((Path(parent) / name).relative_to(root)))
            if len(actual) > MAX_FILES:
                raise ValueError("Application file capacity exceeded")
    if actual != set(entries):
        return "MISMATCH", "APPLICATION_INVENTORY_CHANGED", {}
    manifest, total = {}, 0
    for name, (expected_hash, expected_size) in sorted(entries.items()):
        if (
            not expected_hash.startswith("sha256=")
            or not expected_size.isdigit()
            or len(expected_size) > 10
        ):
            return "UNAVAILABLE", "INSTALLATION_HASH_UNAVAILABLE", {}
        raw = _read(root / name, min(1024 * 1024, MAX_BYTES - total))
        total += len(raw)
        digest = hashlib.sha256(raw).digest()
        if (
            len(raw) != int(expected_size)
            or base64.urlsafe_b64encode(digest).decode().rstrip("=") != expected_hash[7:]
        ):
            return "MISMATCH", "APPLICATION_CONTENT_CHANGED", {}
        manifest[name] = digest.hex()
    wheel = metadata.get("archive_info", {}).get("hashes", {}).get("sha256")
    return (
        "VERIFIED_FILES",
        None,
        {
            "package_version": headers["Version"],
            "application_sha256": hashlib.sha256(
                json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "wheel_sha256": wheel,
            "file_count": len(manifest),
        },
    )


def inspect_release(*, now=None):
    """Inspect this imported package once; never read Git, credentials or the network.

    RECORD consistency is local evidence. The wheel pin is installer-declared
    provenance, not independent approval. No dependency or loaded-memory claim.
    """
    at = now if now is not None else utc_now()
    try:
        status, reason, values = _inspect(importlib.metadata.distribution(PACKAGE), app.__file__)
        return InstalledRelease(
            status=status,
            reason=reason,
            observed_at=at,
            python_version=platform.python_version(),
            **values,
        )
    except importlib.metadata.PackageNotFoundError:
        reason = "PACKAGE_NOT_INSTALLED"
    except (OSError, ValueError, TypeError, AttributeError, csv.Error):
        reason = "INSTALLATION_INSPECTION_FAILED"
    return InstalledRelease(
        status="UNAVAILABLE",
        reason=reason,
        observed_at=at,
        python_version=platform.python_version(),
    )


def stored_release(db, generation):
    """Observer projection only. It does not inspect the observer's package files."""
    row = db.execute(
        "SELECT payload FROM execution_events WHERE kind='OPTION_RUNTIME_STARTED' ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    if len(row[0]) > 8192:
        raise ValueError("Bounded runtime start evidence required")
    payload = json.loads(row[0])
    if not isinstance(payload, dict):
        raise TypeError("Runtime start evidence must be an object")
    if "release" not in payload:
        return None
    if type(payload.get("generation")) is not int or payload["generation"] != generation:
        raise ValueError("Release identity belongs to a different runtime generation")
    return InstalledRelease.model_validate(payload["release"]).model_dump(mode="json")
