"""Pure-unit tests for RRF fusion — no DB, no network."""
from app.retrieval.fusion import rrf_fuse


def test_rrf_single_list_orders_by_rank():
    result = rrf_fuse(["a", "b", "c"])
    ids = [r[0] for r in result]
    assert ids == ["a", "b", "c"]
    assert result[0][1] > result[1][1] > result[2][1]


def test_rrf_overlap_boosts_shared_item():
    # "b" appears rank-1 in list2 and rank-2 in list1 — should outscore "a" (only list1)
    result = rrf_fuse(["a", "b"], ["b", "c"])
    scores = {r[0]: r[1] for r in result}
    assert scores["b"] > scores["a"]
    assert scores["b"] > scores["c"]


def test_rrf_no_overlap_equal_rank1_scores():
    result = rrf_fuse(["a"], ["b"])
    scores = {r[0]: r[1] for r in result}
    assert scores["a"] == scores["b"]


def test_rrf_empty_lists():
    assert rrf_fuse([]) == []
    assert rrf_fuse([], []) == []


def test_rrf_returns_sorted_descending():
    result = rrf_fuse(["x", "y", "z"], ["z", "y"])
    scores = [r[1] for r in result]
    assert scores == sorted(scores, reverse=True)
