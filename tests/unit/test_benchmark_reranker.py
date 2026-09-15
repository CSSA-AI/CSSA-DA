import json

import pytest

from ops import benchmark_reranker


def make_records(count):
    return [
        {"question_text": f"问题 {i}", "content": f"正文 {i} " * 20}
        for i in range(count)
    ]


class FakeModel:
    max_seq_length = 128

    def __init__(self):
        self.calls = []

    def predict(self, pairs):
        self.calls.append(list(pairs))
        return [0.0] * len(pairs)


def test_percentile_uses_nearest_rank():
    values = list(range(1, 101))

    assert benchmark_reranker.percentile(values, 50) == 50
    assert benchmark_reranker.percentile(values, 95) == 95
    assert benchmark_reranker.percentile([30, 10, 20], 50) == 20
    assert benchmark_reranker.percentile([30, 10, 20], 95) == 30


@pytest.mark.parametrize("values, q", [([], 50), ([1.0], 0), ([1.0], 101)])
def test_percentile_rejects_invalid_input(values, q):
    with pytest.raises(ValueError):
        benchmark_reranker.percentile(values, q)


def test_load_records_skips_records_the_reranker_cannot_score(tmp_path):
    corpus = tmp_path / "corpus.json"
    corpus.write_text(
        json.dumps(
            [
                {"question_text": "有效", "content": "正文"},
                {"question_text": "", "content": "没有问题"},
                {"question_text": "没有正文", "content": "   "},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    records = benchmark_reranker.load_records(corpus)

    assert records == [{"question_text": "有效", "content": "正文"}]


def test_build_requests_uses_distinct_real_passages_per_pool():
    records = make_records(50)

    requests = benchmark_reranker.build_requests(records, pool_size=30, count=5, seed=7)

    assert len(requests) == 5
    for query, passages in requests:
        assert len(passages) == 30
        assert len(set(passages)) == 30
        assert query in {record["question_text"] for record in records}


def test_build_requests_is_deterministic_for_a_seed():
    records = make_records(50)

    first = benchmark_reranker.build_requests(records, pool_size=10, count=3, seed=7)
    second = benchmark_reranker.build_requests(records, pool_size=10, count=3, seed=7)

    assert first == second


def test_build_requests_refuses_a_corpus_smaller_than_the_pool():
    with pytest.raises(ValueError, match="need at least 30"):
        benchmark_reranker.build_requests(make_records(10), pool_size=30, count=1, seed=7)


def test_time_requests_excludes_warmup_from_timings():
    model = FakeModel()
    requests = benchmark_reranker.build_requests(make_records(20), pool_size=5, count=4, seed=7)

    timings = benchmark_reranker.time_requests(model, requests, warmup=1)

    assert len(timings) == 3
    assert len(model.calls) == 4
    assert all(len(call) == 5 for call in model.calls)


def test_main_records_conditions_next_to_the_numbers(tmp_path, capsys):
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps(make_records(40), ensure_ascii=False), encoding="utf-8")
    model = FakeModel()
    loaded = {}

    def factory(name, revision, max_length, trust_remote_code):
        loaded.update(name=name, revision=revision, max_length=max_length, remote=trust_remote_code)
        return model

    exit_code = benchmark_reranker.main(
        [
            "--corpus", str(corpus),
            "--model", "example/reranker",
            "--revision", "abc123",
            "--max-length", "256",
            "--pool-size", "8",
            "--threads", "1",
            "--threads", "2",
            "--requests", "3",
            "--warmup", "1",
        ],
        model_factory=factory,
    )

    assert exit_code == 0
    assert loaded == {"name": "example/reranker", "revision": "abc123", "max_length": 256, "remote": False}
    reports = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [report["threads"] for report in reports] == [1, 2]
    for report in reports:
        assert report["pool_size"] == 8
        assert report["requests"] == 3
        assert report["max_length"] == 256
        assert report["effective_max_length"] == 128
        assert {"machine", "processor", "deployment_architecture"} <= set(report["hardware"])
        assert report["p50_ms"] <= report["p95_ms"]


def test_describe_hardware_flags_only_arm64_as_the_deployment_architecture(monkeypatch):
    monkeypatch.setattr(benchmark_reranker, "cpu_name", lambda: "Example CPU")

    for machine, expected in [("aarch64", True), ("arm64", True), ("AMD64", False), ("x86_64", False)]:
        monkeypatch.setattr(benchmark_reranker.platform, "machine", lambda m=machine: m)
        hardware = benchmark_reranker.describe_hardware()
        assert hardware["processor"] == "Example CPU"
        assert hardware["deployment_architecture"] is expected


def test_main_defaults_to_the_configured_reranker(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps(make_records(40), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setitem(
        benchmark_reranker.rag_config,
        "reranker",
        {"model_name": "configured/reranker", "model_revision": "pinned-sha", "max_length": 512},
    )
    monkeypatch.setitem(benchmark_reranker.rag_config, "retriever", {"top_k": 12})
    loaded = {}

    def factory(name, revision, max_length, trust_remote_code):
        loaded.update(name=name, revision=revision, max_length=max_length)
        return FakeModel()

    benchmark_reranker.main(
        ["--corpus", str(corpus), "--threads", "1", "--requests", "1", "--warmup", "0"],
        model_factory=factory,
    )

    assert loaded == {"name": "configured/reranker", "revision": "pinned-sha", "max_length": 512}
