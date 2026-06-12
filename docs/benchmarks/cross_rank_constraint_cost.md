# Cross-rank constraint cost — ADR 0038 §"v1 scope gate"

Last run: 2026-06-12 03:50:02 UTC

## Thresholds (ADR 0038 §"v1 scope gate", 10k × 4 ranks)

- `deck_emit_sec     < 5.0`
- `deck_parse_py_sec < 2.0`
- `deck_lines        < 500_000`
- `peak_rss_mb       < 1500.0`

## Results

| interface_size | ranks | element_kind | deck_lines | deck_emit_sec | deck_parse_py_sec | peak_rss_mb | pass_at_10k×4 |
|---:|---:|---|---:|---:|---:|---:|:---:|
| 100 | 2 | tet_host_line_embed | 1_014 | 0.011 | 0.011 | 199.8 | — |
| 100 | 2 | hex_host_line_embed | 1_414 | 0.010 | 0.017 | 203.3 | — |
| 100 | 4 | tet_host_line_embed | 1_020 | 0.008 | 0.010 | 203.3 | — |
| 100 | 4 | hex_host_line_embed | 1_420 | 0.012 | 0.018 | 203.5 | — |
| 100 | 8 | tet_host_line_embed | 1_032 | 0.011 | 0.009 | 203.5 | — |
| 100 | 8 | hex_host_line_embed | 1_432 | 0.013 | 0.018 | 204.2 | — |
| 1_000 | 2 | tet_host_line_embed | 10_014 | 0.066 | 0.131 | 258.9 | — |
| 1_000 | 2 | hex_host_line_embed | 14_014 | 0.083 | 0.192 | 284.8 | — |
| 1_000 | 4 | tet_host_line_embed | 10_020 | 0.074 | 0.130 | 284.8 | — |
| 1_000 | 4 | hex_host_line_embed | 14_020 | 0.101 | 0.192 | 287.8 | — |
| 1_000 | 8 | tet_host_line_embed | 10_032 | 0.085 | 0.127 | 287.8 | — |
| 1_000 | 8 | hex_host_line_embed | 14_032 | 0.262 | 0.161 | 287.8 | — |
| 10_000 | 2 | tet_host_line_embed | 100_014 | 0.708 | 1.349 | 822.5 | — |
| 10_000 | 2 | hex_host_line_embed | 140_014 | 1.202 | 2.010 | 1037.6 | — |
| 10_000 | 4 | tet_host_line_embed | 100_020 | 0.833 | 1.358 | 1037.6 | PASS |
| 10_000 | 4 | hex_host_line_embed | 140_020 | 1.264 | 1.854 | 1038.5 | PASS |
| 10_000 | 8 | tet_host_line_embed | 100_032 | 1.019 | 1.329 | 1038.5 | — |
| 10_000 | 8 | hex_host_line_embed | 140_032 | 1.493 | 2.077 | 1038.5 | — |
| 100_000 | 2 | tet_host_line_embed | 1_000_014 | 7.472 | 16.934 | 6025.0 | — |
| 100_000 | 2 | hex_host_line_embed | 1_400_014 | 12.585 | 21.601 | 9054.9 | — |
| 100_000 | 4 | tet_host_line_embed | 1_000_020 | 7.320 | 13.287 | 9054.9 | — |
| 100_000 | 4 | hex_host_line_embed | 1_400_020 | 10.189 | 18.832 | 9054.9 | — |
| 100_000 | 8 | tet_host_line_embed | 1_000_032 | 7.704 | 12.249 | 9054.9 | — |
| 100_000 | 8 | hex_host_line_embed | 1_400_032 | 11.743 | 19.551 | 9054.9 | — |

## Decision gate status

- `deck_emit_sec`     pass: **True**
- `deck_parse_py_sec` pass: **True**
- `deck_lines`        pass: **True**
- `peak_rss_mb`       pass: **True**

**Overall: PASS** — proceed to Phase 2 (full feature).
