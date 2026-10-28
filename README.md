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

`SampleStore.load()` also accepts an optional `encoding` argument when loading from a file path. Records are decoded to Unicode when loaded and returned as strings by `sample()`.

Sampling more records than remain raises an error and does not change the cache. Run the tests with `python -m unittest`.