"""Runtime device detection for transcription backends.

Probes whether CUDA is usable *right now* — not just whether a GPU exists,
but whether the current install has a CUDA-capable build of CTranslate2
(for Whisper) and onnxruntime-gpu (for Parakeet). Cached so the probe runs
once per process.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeviceInfo:
    ctranslate2_cuda: bool   # faster-whisper can use CUDA
    onnx_cuda: bool          # onnxruntime has CUDAExecutionProvider available
    gpu_name: str | None

    @property
    def any_gpu(self) -> bool:
        return self.ctranslate2_cuda or self.onnx_cuda


@lru_cache(maxsize=1)
def detect() -> DeviceInfo:
    ct2_cuda = _probe_ctranslate2_cuda()
    onnx_cuda, gpu_name = _probe_onnx_cuda()
    info = DeviceInfo(
        ctranslate2_cuda=ct2_cuda,
        onnx_cuda=onnx_cuda,
        gpu_name=gpu_name,
    )
    logger.info(
        f"Device detection: ctranslate2_cuda={ct2_cuda}, "
        f"onnx_cuda={onnx_cuda}, gpu={gpu_name or 'none'}"
    )
    return info


def _probe_ctranslate2_cuda() -> bool:
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception as e:
        logger.debug(f"ctranslate2 CUDA probe failed: {e}")
        return False


def _probe_onnx_cuda() -> tuple[bool, str | None]:
    try:
        import onnxruntime as ort
        providers = ort.get_available_providers()
        if "CUDAExecutionProvider" not in providers:
            return False, None
        # CUDAExecutionProvider is registered; try a zero-cost device query.
        try:
            import onnxruntime.capi._pybind_state as C  # type: ignore
            name = getattr(C, "get_default_cuda_device", lambda: None)()
            if isinstance(name, str):
                return True, name
        except Exception:
            pass
        return True, "cuda"
    except Exception as e:
        logger.debug(f"onnxruntime CUDA probe failed: {e}")
        return False, None
