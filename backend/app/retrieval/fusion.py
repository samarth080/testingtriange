"""Reciprocal Rank Fusion over multiple ranked lists."""


def rrf_fuse(*ranked_lists: list[str], k: int = 60) -> list[tuple[str, float]]:
    """
    Fuse ranked lists using Reciprocal Rank Fusion.

    Args:
        *ranked_lists: Each list is ordered best-first (index 0 = rank 1).
        k: RRF constant (default 60, from the Cormack et al. 2009 paper).

    Returns:
        List of (id, rrf_score) sorted by score descending.
    """
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, item_id in enumerate(ranked, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
