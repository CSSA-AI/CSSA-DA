"""Benchmark reranker latency on CPU, with the conditions recorded next to the numbers.

Issue #90 makes latency a selection criterion and requires every number to state
the pool size, the pinned thread count and the hardware it came from. This script
exists so those numbers are reproducible rather than one-off: run it on the
deployment architecture (arm64 Graviton) and the result is directly comparable
with a run on any other machine.

    python ops/benchmark_reranker.py --threads 2
    python ops/benchmark_reranker.py --threads 2 --threads 4
    python ops/benchmark_reranker.py --threads 2 \
        --model BAAI/bge-reranker-v2-m3 --revision <sha> --max-length 512

Without --model it benchmarks the reranker configured in rag-config.yaml, i.e.
the one that ships. Pool size defaults to retriever.top_k, which is how many
candidates the reranker scores per request in production.

Only real hardware counts. arm64 timings taken under QEMU emulation (for
example `docker run --platform linux/arm64` on an x86 host) measure the emulator,
not the CPU, and must not be reported as arm64 numbers.
"""

import argparse
import io
import json
import math
import os
import platform
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import rag_config  # noqa: E402


DEFAULT_CORPUS = PROJECT_ROOT / "data" / "current" / "wechat_articles_processed.json"
DEPLOYMENT_ARCHITECTURES = ("aarch64", "arm64")

Pair = tuple[str, str]
Request = tuple[str, list[str]]


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile: the smallest value with at least q% of samples at or below it."""
    if not values:
        raise ValueError("percentile of an empty sequence")
    if not 0 < q <= 100:
        raise ValueError("q must be in (0, 100]")
    ordered = sorted(values)
    rank = math.ceil(q / 100 * len(ordered))
    return ordered[rank - 1]


def load_records(path: Path) -> list[dict[str, Any]]:
    """Read processed knowledge-base records, keeping those the reranker could score."""
    with io.open(path, encoding="utf-8") as handle:
        records = json.load(handle)
    return [
        record
        for record in records
        if (record.get("question_text") or "").strip() and (record.get("content") or "").strip()
    ]


def build_requests(
    records: Sequence[dict[str, Any]],
    pool_size: int,
    count: int,
    seed: int,
) -> list[Request]:
    """Build `count` rerank requests, each a query plus `pool_size` distinct real passages.

    Latency is dominated by passage length after truncation, so the pools use real
    corpus passages rather than synthetic text.
    """
    if pool_size < 1 or count < 1:
        raise ValueError("pool_size and count must be at least 1")
    if len(records) < pool_size:
        raise ValueError(f"corpus has {len(records)} usable records, need at least {pool_size}")
    rng = random.Random(seed)
    requests: list[Request] = []
    for _ in range(count):
        pool = rng.sample(range(len(records)), pool_size)
        query = records[pool[0]]["question_text"]
        requests.append((query, [records[index]["content"] for index in pool]))
    return requests


def cpu_name() -> str:
    """Best-effort human-readable CPU model; the hardware claim is only as good as this."""
    if sys.platform == "win32":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            )
            return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        except OSError:
            return platform.processor()
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text(errors="ignore").splitlines():
            if line.lower().startswith(("model name", "cpu model")):
                return line.split(":", 1)[1].strip()
    # arm64 Linux (including Graviton) has no "model name" in /proc/cpuinfo;
    # lscpu decodes the CPU part into a name such as "Neoverse-V1".
    try:
        output = subprocess.run(["lscpu"], capture_output=True, text=True, timeout=5).stdout
        for line in output.splitlines():
            if line.startswith("Model name:"):
                return line.split(":", 1)[1].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return platform.processor()


def describe_hardware() -> dict[str, Any]:
    machine = platform.machine()
    processor = cpu_name()
    return {
        "machine": machine,
        "processor": processor,
        "system": platform.system(),
        "python": platform.python_version(),
        "logical_cpus": os.cpu_count(),
        "deployment_architecture": machine.lower() in DEPLOYMENT_ARCHITECTURES,
    }


def time_requests(model: Any, requests: Sequence[Request], warmup: int) -> list[float]:
    """Return per-request latency in milliseconds, after `warmup` untimed requests."""
    for query, passages in requests[:warmup]:
        model.predict([(query, passage) for passage in passages])
    timings = []
    for query, passages in requests[warmup:]:
        pairs: list[Pair] = [(query, passage) for passage in passages]
        start = time.perf_counter()
        model.predict(pairs)
        timings.append((time.perf_counter() - start) * 1000)
    return timings


def load_cross_encoder(model: str, revision: str | None, max_length: int | None, trust_remote_code: bool):
    from sentence_transformers import CrossEncoder

    kwargs: dict[str, Any] = {"device": "cpu", "trust_remote_code": trust_remote_code}
    if revision:
        kwargs["revision"] = revision
    if max_length:
        kwargs["max_length"] = max_length
    return CrossEncoder(model, **kwargs)


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    reranker = rag_config["reranker"]
    parser = argparse.ArgumentParser(description="Benchmark reranker latency on CPU.")
    parser.add_argument("--model", default=None, help="Model id; defaults to the configured reranker.")
    parser.add_argument("--revision", default=None, help="Pinned revision; defaults to the configured one.")
    parser.add_argument(
        "--max-length",
        type=int,
        default=None,
        help="Truncation length; defaults to reranker.max_length in rag-config.yaml.",
    )
    parser.add_argument(
        "--threads",
        type=int,
        action="append",
        required=True,
        help="Torch intra-op threads to pin. Repeat to benchmark several settings.",
    )
    parser.add_argument(
        "--pool-size",
        type=int,
        default=rag_config["retriever"]["top_k"],
        help="Candidates scored per request; defaults to retriever.top_k.",
    )
    parser.add_argument("--requests", type=int, default=30, help="Timed requests per thread setting.")
    parser.add_argument("--warmup", type=int, default=3, help="Untimed requests before timing.")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--seed", type=int, default=20260915)
    parser.add_argument("--trust-remote-code", action="store_true")
    args = parser.parse_args(argv)

    if args.model is None:
        args.model = reranker["model_name"]
        args.revision = args.revision or reranker.get("model_revision")
    if args.max_length is None:
        args.max_length = reranker.get("max_length")
    if args.requests < 1 or args.warmup < 0 or any(t < 1 for t in args.threads):
        parser.error("--requests and --threads must be at least 1, --warmup at least 0")
    return args


def main(
    argv: Sequence[str] | None = None,
    model_factory: Callable[..., Any] = load_cross_encoder,
) -> int:
    import torch

    args = parse_args(argv)
    records = load_records(args.corpus)
    requests = build_requests(records, args.pool_size, args.warmup + args.requests, args.seed)
    model = model_factory(args.model, args.revision, args.max_length, args.trust_remote_code)

    hardware = describe_hardware()
    previous_threads = torch.get_num_threads()
    try:
        for threads in args.threads:
            torch.set_num_threads(threads)
            timings = time_requests(model, requests, args.warmup)
            report = {
                "model": args.model,
                "revision": args.revision,
                "max_length": args.max_length,
                "effective_max_length": getattr(model, "max_seq_length", None),
                "pool_size": args.pool_size,
                "threads": threads,
                "requests": len(timings),
                "warmup": args.warmup,
                "p50_ms": round(percentile(timings, 50), 1),
                "p95_ms": round(percentile(timings, 95), 1),
                "mean_ms": round(sum(timings) / len(timings), 1),
                "torch": torch.__version__,
                "hardware": hardware,
            }
            print(json.dumps(report, ensure_ascii=False))
    finally:
        torch.set_num_threads(previous_threads)

    if not hardware["deployment_architecture"]:
        print(
            f"note: measured on {hardware['machine']}, not the arm64 deployment target; "
            "these numbers show relative cost only.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
