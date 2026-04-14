"""
Shared data structure for all chunkers.

ChunkData is the return type of every chunker function.
The pipeline maps these to Postgres Chunk rows and Qdrant points.
"""
from dataclasses import dataclass, field


@dataclass
class ChunkData:
    text: str           # The text to embed
    chunk_index: int    # 0-based index within the source entity
    metadata: dict = field(default_factory=dict)  # source-specific fields
