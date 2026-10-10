"""Independent, append-only checkpoint bytes. No database parsing or execution authority."""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import re
import socket
import stat
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

MAX_BYTES = 64 * 1024 * 1024
PIN = re.compile(r"[0-9a-f]{64}\Z")
CONFIG = "archive.json"
LEASE = "archive.lock"
INCOMING = "incoming"
OBJECT = "checkpoint.tbcp"


class ArchiveUnavailable(ValueError):
    pass


def _private(info, *, directory=False):
    if (
        not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
        or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
        or info.st_uid != os.geteuid()
    ):
        raise ArchiveUnavailable("Private current-owner archive material required")


def _file(directory, name, flags=os.O_RDONLY):
    fd = os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory)
    try:
        _private(os.fstat(fd))
        return fd
    except BaseException:
        os.close(fd)
        raise


def _directory(path, *, parent=None):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        _private(os.fstat(fd), directory=True)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _json(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ArchiveUnavailable("Duplicate archive configuration field")
        value[key] = item
    return value


def initialize(directory, *, max_objects):
    if type(max_objects) is not int or not 1 <= max_objects <= 1000:
        raise ValueError("Explicit archive capacity between 1 and 1000 required")
    directory = Path(directory).absolute()
    # The operator provisions the parent and filesystem/quota. Never replace a store.
    directory.mkdir(mode=0o700)
    with ArchiveStore(directory, initializing=True) as store:
        fd = _file(store.fd, CONFIG, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        try:
            payload = json.dumps(
                {"schema": "checkpoint-archive-v1", "max_objects": max_objects},
                separators=(",", ":"),
            ).encode()
            with os.fdopen(fd, "wb", closefd=False) as output:
                output.write(payload)
                output.flush()
                os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(store.fd)
        parent = os.open(directory.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    return {"status": "INITIALIZED", "max_objects": max_objects, "execution_authority": False}


class ArchiveStore:
    """A retained private directory and lifetime single-process lease."""

    def __init__(self, directory, *, initializing=False):
        self.fd = _directory(Path(directory).absolute())
        self.lease = None
        try:
            self.lease = _file(self.fd, LEASE, os.O_RDWR | os.O_CREAT)
            fcntl.flock(self.lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.fsync(self.lease)
            os.fsync(self.fd)
            if not initializing:
                fd = _file(self.fd, CONFIG)
                try:
                    if not 0 < os.fstat(fd).st_size <= 1024:
                        raise ArchiveUnavailable("Bounded archive configuration required")
                    raw = json.loads(os.read(fd, 1025), object_pairs_hook=_json)
                finally:
                    os.close(fd)
                if (
                    type(raw) is not dict
                    or set(raw) != {"schema", "max_objects"}
                    or raw["schema"] != "checkpoint-archive-v1"
                    or type(raw["max_objects"]) is not int
                    or not 1 <= raw["max_objects"] <= 1000
                ):
                    raise ArchiveUnavailable("Unsupported archive configuration")
                self.max_objects = raw["max_objects"]
                self.admissions()
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.lease is not None:
            os.close(self.lease)
            self.lease = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def admissions(self):
        _private(os.fstat(self.fd), directory=True)
        pins = []
        # Stop on the first capacity violation, rather than allocating an unbounded listing.
        with os.scandir(self.fd) as entries:
            for entry in entries:
                if entry.name in {CONFIG, LEASE}:
                    continue
                if not PIN.fullmatch(entry.name):
                    raise ArchiveUnavailable("Unrecognized archive admission")
                child = _directory(entry.name, parent=self.fd)
                os.close(child)
                pins.append(entry.name)
                if len(pins) > self.max_objects:
                    raise ArchiveUnavailable("Archive capacity exceeded")
        return sorted(pins)

    @contextmanager
    def object_directory(self, pin):
        if type(pin) is not str or not PIN.fullmatch(pin):
            raise ValueError("Lowercase SHA-256 archive identity required")
        fd = _directory(pin, parent=self.fd)
        try:
            yield fd
        finally:
            os.close(fd)

    def admit(self, pin):
        pins = self.admissions()
        if pin in pins:
            return False
        if len(pins) >= self.max_objects:
            raise ArchiveUnavailable("Archive capacity exhausted")
        if not PIN.fullmatch(pin):
            raise ValueError("Lowercase SHA-256 archive identity required")
        os.mkdir(pin, mode=0o700, dir_fd=self.fd)
        os.fsync(self.fd)
        return True

    @contextmanager
    def verified(self, pin):
        _private(os.fstat(self.fd), directory=True)
        with self.object_directory(pin) as directory:
            fd = _file(directory, OBJECT)
            try:
                size = os.fstat(fd).st_size
                if not 0 < size <= MAX_BYTES:
                    raise ArchiveUnavailable("Archive object size rejected")
                digest = hashlib.sha256()
                with os.fdopen(fd, "rb", closefd=False) as source:
                    while chunk := source.read(65536):
                        digest.update(chunk)
                        if source.tell() > MAX_BYTES:
                            raise ArchiveUnavailable("Archive object size changed")
                if digest.hexdigest() != pin or os.lseek(fd, 0, os.SEEK_CUR) != size:
                    raise ArchiveUnavailable("Archive object digest rejected")
                # A retry after a lost reply/crash must also establish durable publication.
                os.fsync(fd)
                os.fsync(directory)
                os.fsync(self.fd)
                os.lseek(fd, 0, os.SEEK_SET)
                yield fd, size
            finally:
                os.close(fd)

    def report(self):
        observations = []
        for pin in self.admissions():
            try:
                with self.verified(pin) as (_, size):
                    observations.append(
                        {"checkpoint_sha256": pin, "status": "VERIFIED", "byte_count": size}
                    )
            except FileNotFoundError:
                observations.append({"checkpoint_sha256": pin, "status": "INCOMPLETE"})
            except (OSError, ValueError):
                observations.append({"checkpoint_sha256": pin, "status": "UNAVAILABLE"})
        return {
            "schema": "checkpoint-archive-report-v1",
            "max_objects": self.max_objects,
            "admitted_objects": len(observations),
            "objects": observations,
            "off_host_protection": "UNVERIFIED",
            "execution_authority": False,
        }


def private_token(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        _private(os.fstat(fd))
        if os.fstat(fd).st_size not in {64, 65}:
            raise ArchiveUnavailable("Private archive token required")
        token = os.read(fd, 66)
        if len(token) == 65 and token.endswith(b"\n"):
            token = token[:-1]
        if not PIN.fullmatch(token.decode("ascii")):
            raise ArchiveUnavailable("Private archive token required")
        return token.decode("ascii")
    finally:
        os.close(fd)


class ArchiveServer(HTTPServer):
    """One connection at a time; TLS, headers, body and reply share a socket deadline."""

    def __init__(self, address, *, store, context, token_file, authority, timeout_seconds=30):
        if type(timeout_seconds) not in {int, float} or not 0 < timeout_seconds <= 30:
            raise ValueError("A bounded archive connection deadline is required")
        self.store, self.context = store, context
        self.token_file, self.authority = token_file, authority
        self.timeout_seconds = timeout_seconds
        self.deadline = None
        self.timer = None
        private_token(token_file)
        super().__init__(address, ArchiveHandler)
        self.timeout = 0.5

    def get_request(self):
        raw, address = super().get_request()
        self.deadline = time.monotonic() + self.timeout_seconds
        try:
            connection = self.context.wrap_socket(
                raw, server_side=True, do_handshake_on_connect=False
            )
        except BaseException:
            raw.close()
            raise
        connection.settimeout(self.timeout_seconds)

        def expire():
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        self.timer = threading.Timer(self.timeout_seconds, expire)
        self.timer.daemon = True
        self.timer.start()
        try:
            connection.do_handshake()
            return connection, address
        except BaseException:
            self.timer.cancel()
            connection.close()
            raise

    def shutdown_request(self, request):
        if self.timer is not None:
            self.timer.cancel()
        super().shutdown_request(request)

    def handle_error(self, request, client_address):
        # Never log request data, tokens, paths or an unauthenticated traceback.
        pass


class ArchiveHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server_version = "CheckpointArchive"
    sys_version = ""

    def log_message(self, *args):
        pass

    def send_error(self, code, message=None, explain=None):
        self.reply(code, {"status": "UNAVAILABLE"})

    def reply(self, code, value):
        body = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def authorize(self):
        names = [name.lower() for name in self.headers]
        # No proxy authority, URL decoding, browser-origin authority, encodings or ambiguous framing.
        if (
            len(names) > 16
            or any(len(value) > 1024 for _, value in self.headers.items())
            or len(set(names)) != len(names)
            or any(name == "forwarded" or name.startswith("x-forwarded-") for name in names)
            or any(name in names for name in ("transfer-encoding", "origin", "expect"))
            or self.headers.get("host", "").lower() != self.server.authority
        ):
            self.reply(400, {"status": "UNAVAILABLE"})
            return None
        try:
            token = private_token(self.server.token_file)
        except (OSError, ValueError, UnicodeError):
            self.reply(503, {"status": "UNAVAILABLE"})
            return None
        auth = self.headers.get("authorization", "")
        if not hmac.compare_digest(
            hashlib.sha256(auth.encode()).digest(),
            hashlib.sha256(("Bearer " + token).encode()).digest(),
        ):
            self.reply(401, {"status": "UNAVAILABLE"})
            return None
        prefix = "/v1/checkpoints/"
        pin = self.path[len(prefix) :] if self.path.startswith(prefix) else ""
        if not PIN.fullmatch(pin):
            self.reply(404, {"status": "UNAVAILABLE"})
            return None
        return pin

    def do_PUT(self):
        pin = self.authorize()
        if pin is None:
            return
        length = self.headers.get("content-length", "")
        if (
            not length.isascii()
            or not length.isdecimal()
            or len(length) > 8
            or not 0 < int(length) <= MAX_BYTES
            or self.headers.get("content-type") != "application/octet-stream"
            or self.headers.get("content-encoding", "identity") != "identity"
            or self.headers.get("idempotency-key") != pin
        ):
            self.reply(400, {"status": "UNAVAILABLE"})
            return
        size = int(length)
        try:
            created = self.server.store.admit(pin)
            if not created:
                # Incomplete/corrupt admissions are retained and never rewritten on retry.
                with self.server.store.verified(pin) as (_, prior_size):
                    if prior_size != size:
                        raise ArchiveUnavailable("Archive identity size changed")
            with self.server.store.object_directory(pin) as directory:
                fd = (
                    _file(directory, INCOMING, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
                    if created
                    else None
                )
                try:
                    digest, remaining = hashlib.sha256(), size
                    while remaining:
                        if time.monotonic() >= self.server.deadline:
                            raise TimeoutError("Archive connection expired")
                        chunk = self.rfile.read(min(65536, remaining))
                        if not chunk:
                            raise ArchiveUnavailable("Archive body incomplete")
                        digest.update(chunk)
                        if fd is not None:
                            view = memoryview(chunk)
                            while view:
                                written = os.write(fd, view)
                                if written <= 0:
                                    raise OSError("Archive write incomplete")
                                view = view[written:]
                        remaining -= len(chunk)
                    if digest.hexdigest() != pin:
                        raise ArchiveUnavailable("Archive body digest rejected")
                    if time.monotonic() >= self.server.deadline:
                        raise TimeoutError("Archive connection expired")
                    if fd is not None:
                        os.fsync(fd)
                        os.link(
                            INCOMING,
                            OBJECT,
                            src_dir_fd=directory,
                            dst_dir_fd=directory,
                            follow_symlinks=False,
                        )
                        os.fsync(directory)
                        os.fsync(self.server.store.fd)
                        # Publication is already durable; this only removes the staging alias.
                        os.unlink(INCOMING, dir_fd=directory)
                        os.fsync(directory)
                finally:
                    if fd is not None:
                        os.close(fd)
            self.reply(
                201 if created else 200,
                {"checkpoint_sha256": pin, "byte_count": size, "retained": True},
            )
        except (OSError, ValueError):
            self.reply(409, {"status": "UNAVAILABLE"})

    def do_GET(self):
        pin = self.authorize()
        if pin is None:
            return
        if self.headers.get("content-length", "0") != "0":
            self.reply(400, {"status": "UNAVAILABLE"})
            return
        started = False
        try:
            with self.server.store.verified(pin) as (fd, size):
                if time.monotonic() >= self.server.deadline:
                    raise TimeoutError("Archive connection expired")
                started = True
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(size))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                remaining = size
                while remaining:
                    if time.monotonic() >= self.server.deadline:
                        raise TimeoutError("Archive connection expired")
                    chunk = os.read(fd, min(65536, remaining))
                    if not chunk:
                        raise ArchiveUnavailable("Archive object changed")
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except FileNotFoundError:
            self.reply(404, {"status": "UNAVAILABLE"})
        except (OSError, ValueError):
            # If headers were sent, close rather than append an error response to the object.
            if started:
                self.close_connection = True
            else:
                self.reply(503, {"status": "UNAVAILABLE"})
