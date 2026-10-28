# Text Sampler

The server keeps newline-delimited text records in a shared in-memory cache. `POST /load` streams a text file from a client into that cache, and `POST /sample` returns a random selection while removing those records. Files are interpreted as UTF-8 by default; pass an encoding to `load()` for another supported text encoding. A lock protects cache changes, and the threaded HTTP server can handle multiple local clients concurrently.

Start the server with:

```powershell
python server.py
```

Use the Python client from another process:

```python
from server import SampleClient

client = SampleClient()
loaded = client.load("large-text-file.txt", encoding="cp1252")
records = client.sample(10)
```

`SampleStore.load()` and `SampleClient.load()` accept an optional `encoding` argument, defaulting to UTF-8. Each sampled item is a `SampleRecord`: its `data` field contains bytes in the original encoding, and its `encoding` field identifies that encoding. For example, decode a sample with `record.data.decode(record.encoding)`. Over HTTP, bytes are base64-encoded in JSON and decoded by `SampleClient`.

### When a sample request exceeds the available records

There are several reasonable policies for `sample(N)` when fewer than `N` records are cached:

- **Fail immediately (current behavior):** raise an error (`ValueError` in `SampleStore`, HTTP 409 through the client) and leave the cache unchanged. This keeps the request all-or-nothing and makes shortages explicit.
- **Return what is available:** return and remove up to the number of cached records. This is convenient when partial results are useful, but callers must check how many records they received.
- **Wait for records:** hold the request until enough records are loaded, optionally with a timeout. This can suit streaming producers and consumers, but requires timeout/cancellation behavior and careful coordination between concurrent clients.
- **Refill or retry:** load more records from a configured source or ask the caller to retry. This is useful when the cache is backed by a durable source, but needs a defined source and retry policy.

The current fail-immediately behavior is atomic: if there are not enough records, none are removed. Run the tests with `python -m unittest`.