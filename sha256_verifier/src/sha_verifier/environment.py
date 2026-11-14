"""Identity of the simulator the verifier is running on.

Receipts record these values so a result can be tied to an exact Kickmix build.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import platform

import kickmix as km
import numpy as np

# The Kickmix release this verifier is written against. `pyproject.toml` pins the same
# version and `uv.lock` pins the hashes of its wheels.
EXPECTED_KICKMIX_VERSION = '1.0.0'


def kickmix_version() -> str:
    """The installed Kickmix distribution version.

    `km.__version__` still reports `0.1` in the 1.0.0 release, so the distribution
    metadata is the reliable source.
    """
    return importlib.metadata.version('kickmix')


def kickmix_binary_sha256() -> str:
    with open(km.__file__, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def describe() -> dict:
    return {
        'kickmix_version': kickmix_version(),
        'kickmix_binary_sha256': kickmix_binary_sha256(),
        'numpy_version': np.__version__,
        'python_version': platform.python_version(),
        'platform': platform.platform(),
        'machine': platform.machine(),
    }
