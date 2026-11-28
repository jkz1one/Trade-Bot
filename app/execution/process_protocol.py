"""Shared fixed-child bounds and test faults, without parent orchestration."""

import os
import time
from typing import Literal

MAX_REQUEST_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024

FixtureFault = Literal[
    "NONE",
    "STALL_BEFORE_ACCEPT",
    "STALL_AFTER_ACCEPT",
    "IGNORE_TERM_AFTER_ACCEPT",
    "CRASH_AFTER_ACCEPT",
    "LOST_ACK",
    "INVALID_ACK",
    "OVERSIZED_ACK",
    "STALL_READ",
]


def _stall(parent_pid):
    while True:
        if os.getppid() != parent_pid:
            os._exit(96)
        time.sleep(1)

