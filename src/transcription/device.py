"""Runtime device detection for transcription.

Probes whether CUDA is usable *right now* — not just whether a GPU exists,
but whether the current install has a CUDA-capable build of CTranslate2
(for Whisper). Cached so the probe runs once per process.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeviceInfo:
    ctranslate2_cuda: bool   # faster-whisper can use CUDA
    gpu_name: str | None

    @property
    def any_gpu(self) -> bool:
        return self.ctranslate2_cuda


@lru_cache(maxsize=1)
def detect() -> DeviceInfo:
    ct2_cuda = _probe_ctranslate2_cuda()
    info = DeviceInfo(
        ctranslate2_cuda=ct2_cuda,
        gpu_name="cuda" if ct2_cuda else None,
    )
    logger.info(
        f"Device detection: ctranslate2_cuda={ct2_cuda}, "
        f"gpu={info.gpu_name or 'none'}"
    )
    return info


def _probe_ctranslate2_cuda() -> bool:
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception as e:
        logger.debug(f"ctranslate2 CUDA probe failed: {e}")
        return False
