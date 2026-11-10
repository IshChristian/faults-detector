"""The tracks.parquet schema and its read/write helpers."""

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

TRACKS_SCHEMA = pa.schema(
    [
        ("video_id", pa.string()),
        ("t_ms", pa.int64()),  # session timeline
        ("track_id", pa.int32()),
        ("cls", pa.int8()),
        ("x1", pa.float32()),  # boxes are relative 0-1
        ("y1", pa.float32()),
        ("x2", pa.float32()),
        ("y2", pa.float32()),
        ("score", pa.float32()),
    ]
)


def write_tracks(rows: pa.Table, dest: Path) -> None:
    pq.write_table(rows.cast(TRACKS_SCHEMA), dest, compression="zstd")


def read_tracks(path: Path) -> pa.Table:
    return pq.read_table(path, schema=TRACKS_SCHEMA)
