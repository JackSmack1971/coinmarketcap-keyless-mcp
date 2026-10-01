# Mutation survivor review

**Date:** 2026-10-01
**Command:** `uv run mutmut run --max-children 4`, then `uv run python scripts/mutation_gate.py --min-score 0`
**Environment:** Linux, CPython 3.11, mutmut from the locked dev group.

## Result

| | Mutants | Killed | Timeout | Survived | Score |
| --- | ---: | ---: | ---: | ---: | ---: |
| Before review (selection widened, no new tests) | 1001 | 694 | 3 | 304 | 69.6% |
| After `test_client_contract.py`, first pass | 998 | 910 | 3 | 85 | 91.5% |
| **Final** | **998** | **925** | **3** | **70** | **93.0%** |

The score is (killed + timeout) / all mutants. CI enforces a minimum of **92%** (`.github/workflows/ci.yml`), a little below the final score to leave room for timeouts that vary between runs. Raise it as more survivors are killed; never lower it to get a pass.

## What the review changed

- **Mutmut test selection:** added `tests/unit/test_resource_stress.py`, `tests/security/test_h5.py` and `tests/unit/test_client_contract.py`. The first two already covered most of the cache, request-sharing, decoder and depth code, but mutmut wasn't running them. Two subprocess tests are deselected, because they import the installed package rather than mutmut's mutated copy.
- **New tests** (`tests/unit/test_client_contract.py`, plus additions to `test_models.py` and `tests/mcp/test_tools.py`):
  - exact error code, message, status code, attempt count and provider code on every client error path, including after a retry;
  - boundaries: response size, `Content-Length` with leading or trailing zeros, depth 256/257, `Retry-After` exactly at the cap, the 4096-byte error-body read limit, and provider message sanitizing;
  - decoder output bounds on compressible and incompressible data, one-byte deflate chunks, and trailing bytes;
  - exact cache key format, routes as part of the key, LRU order on re-set, purging at the exact expiry time, and copies for callers that share a fetch;
  - default headers, timeout and call metadata, and the cache-hit and cache-miss debug logs;
  - validation messages, the MCP server identity, and the combined-selector error text.
- **Dead code removed:** the unused `KeylessHttpClient._cache_enabled` attribute, and an unreachable `"<name> must not be empty"` branch in `require_exactly_one_selector`. The filter just above that branch already drops empty selectors.

## Remaining 70 survivors: all equivalent

None of these can change behaviour that a caller or the provider can observe.

| Group | Count | Mutants (function#id) | Why equivalent |
| --- | ---: | --- | --- |
| Header-name case | 11 | `__init__#88,89,93,94`; `_fetch#34,35`; `_retry_delay#5,6`; `_bounded_decoded_chunks#10,11,13` | httpx header lookup is case-insensitive, and the encoding value is `.lower()`ed. |
| HTTP method case | 1 | `_fetch#16` | httpx upper-cases the method. |
| Redundant size truncation | 5 | `_fetch#59,60,62`; `_bounded_decoded_chunks#2,19` | The truncation only saves memory; the `len(body) > max` check that follows raises the same error. |
| Unreachable branches | 6 | `_fetch#7` (extra loop iteration after a guaranteed return or raise); `_fetch#174,175,176` (`AssertionError` text after the loop); `_fetch#28,29` (status 400 is already handled by the 4xx branch) | The mutated code can't run. |
| `Content-Length` normalisation | 1 | `_fetch#42` | `lstrip("XX0XX")` and `lstrip("0")` are the same on a decimal string. |
| Unused falsy value | 1 | `_fetch#18` | `""` and `None` are both falsy where `error_detail` is tested. |
| Throwaway `Response` request | 2 | `_fetch#83,86` | The rebuilt response's `request` is never read. |
| Re-parsing already-validated bytes | 11 | `get#38,39,43,44` (cache hit); `get#53,88,91,92` (shared-fetch result); `_parse#6` (thread threshold `>=`); `get#16,21` (`ttl == 0` path, unused key) | Parsing bytes that already passed validation can't fail, so the status and attempt arguments are never seen. The leader/follower choice and the thread threshold only affect performance. |
| Duplicate-key error text | 4 | `_unique_object#3,4,5,6` | The `ValueError` text is replaced by "was not valid JSON". |
| Shared-fetch cleanup guard | 1 | `_finish_inflight#3` | An entry is removed only in this callback, so it is never `None` when the callback runs. |
| `zlib` window bits | 2 | `_bounded_decoded_chunks#79`; `_wbits#5` | `MAX_WBITS \| 17 == MAX_WBITS \| 16 == 31`. |
| zlib header check | 1 | `_wbits#16` | It only differs for a raw deflate stream whose first byte has low nibble 8. That would be a stored block with non-zero padding bits, which zlib never emits. A brute-force search over levels, strategies and sizes found none. |
| Waiting for the first deflate bytes | 2 | `_bounded_decoded_chunks#47,48` | Waiting for 3 header bytes instead of 2 changes nothing. |
| Decoder after the limit or at the end | 12 | `_bounded_decoded_chunks#58,75,80,81` (stop or tail handling once output reaches the limit or the stream ends); `#85,89,93,94,95` (end-of-stream path, reachable only for a 0–1 byte deflate body, which can only be empty); `#96,98,100` (`flush()`; all output is already returned by `decompress` unless the limit was hit, and then the generator has already returned) | The output and the errors are the same. |
| Sanitizer boundaries | 3 | `_safe_provider_error_message#15,16` (space becomes space); `#21` (U+00A0 becomes space, and `str.split()` already treats U+00A0 as whitespace) | Same result. |
| Cache key default | 1 | `cache_key#7` | Removing `ensure_ascii=True` falls back to the same default. |
| `pop` default | 1 | `_TtlCache.get#8` | The key is known to be present. |
| ContextVar name | 1 | `__init__#76` | The name is only used in its `repr`. |
| ISO `Z` handling | 2 | `validate_time#12,13` | Python 3.11+ `fromisoformat` accepts `Z` directly. |
| Distribution-name case | 1 | `create_server#14` | `importlib.metadata.version` normalises the name. |
| Schema aliases | 1 | `create_server#30` | No tool argument has an alias. |
| **Total** | **70** | | |

Timeouts (3) count as detected. They are mutants that make the retry or backoff loop spin until mutmut's timeout.
