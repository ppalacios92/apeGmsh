# Cross-rank constraint cost — ADR 0038 §"v1 scope gate"

Last run: 2026-05-26 17:05:06 UTC

## Thresholds (ADR 0038 §"v1 scope gate", 10k × 4 ranks)

- `deck_emit_sec     < 5.0`
- `deck_parse_py_sec < 2.0`
- `deck_lines        < 500_000`
- `peak_rss_mb       < 1500.0`

## Results

| interface_size | ranks | element_kind | deck_lines | deck_emit_sec | deck_parse_py_sec | peak_rss_mb | pass_at_10k×4 |
|---:|---:|---|---:|---:|---:|---:|:---:|
| 100 | 2 | tet_host_line_embed | 1_014 | 0.036 | 0.012 | 111.1 | — |
| 100 | 2 | hex_host_line_embed | 1_414 | 0.007 | 0.019 | 112.8 | — |
| 100 | 4 | tet_host_line_embed | 1_020 | 0.006 | 0.012 | 114.6 | — |
| 100 | 4 | hex_host_line_embed | 1_420 | 0.009 | 0.018 | 113.0 | — |
| 100 | 8 | tet_host_line_embed | 1_032 | 0.007 | 0.012 | 113.0 | — |
| 100 | 8 | hex_host_line_embed | 1_432 | 0.010 | 0.018 | 113.4 | — |
| 1_000 | 2 | tet_host_line_embed | 10_014 | 0.051 | 0.146 | 118.6 | — |
| 1_000 | 2 | hex_host_line_embed | 14_014 | 0.071 | 0.202 | 160.7 | — |
| 1_000 | 4 | tet_host_line_embed | 10_020 | 0.056 | 0.120 | 165.2 | — |
| 1_000 | 4 | hex_host_line_embed | 14_020 | 0.080 | 0.177 | 165.7 | — |
| 1_000 | 8 | tet_host_line_embed | 10_032 | 0.067 | 0.121 | 170.0 | — |
| 1_000 | 8 | hex_host_line_embed | 14_032 | 0.092 | 0.176 | 163.9 | — |
| 10_000 | 2 | tet_host_line_embed | 100_014 | 0.581 | 1.451 | 323.9 | — |
| 10_000 | 2 | hex_host_line_embed | 140_014 | 0.804 | 1.958 | 334.7 | — |
| 10_000 | 4 | tet_host_line_embed | 100_020 | 0.611 | 1.354 | 489.2 | PASS |
| 10_000 | 4 | hex_host_line_embed | 140_020 | 0.912 | 1.920 | 499.6 | PASS |
| 10_000 | 8 | tet_host_line_embed | 100_032 | 0.755 | 1.333 | 340.6 | — |
| 10_000 | 8 | hex_host_line_embed | 140_032 | 1.051 | 1.975 | 346.0 | — |
| 100_000 | 2 | tet_host_line_embed | 1_000_014 | 5.413 | 14.632 | 2591.1 | — |
| 100_000 | 2 | hex_host_line_embed | 1_400_014 | 7.773 | 20.229 | 4988.3 | — |
| 100_000 | 4 | tet_host_line_embed | 1_000_020 | 6.030 | 13.111 | 4960.4 | — |
| 100_000 | 4 | hex_host_line_embed | 1_400_020 | 8.703 | 19.188 | 4991.5 | — |
| 100_000 | 8 | tet_host_line_embed | 1_000_032 | 7.434 | 13.127 | 4950.6 | — |
| 100_000 | 8 | hex_host_line_embed | 1_400_032 | 10.414 | 19.673 | 5031.9 | — |

## Decision gate status

- `deck_emit_sec`     pass: **True**
- `deck_parse_py_sec` pass: **True**
- `deck_lines`        pass: **True**
- `peak_rss_mb`       pass: **True**

**Overall: PASS** — proceed to Phase 2 (full feature).
