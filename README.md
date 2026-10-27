# Text Sampler

The server keeps newline-delimited text records in a shared in-memory cache. `POST /load` streams a UTF-8 file from a client into that cache, and `POST /sample` returns a random selection while removing those records. A lock protects cache changes, and the threaded HTTP server can handle multiple local clients concurrently.

Start the server with:

```powershell
python server.py
```

Use the Python client from another process:

```python
from server import SampleClient

client = SampleClient()
loaded = client.load("large-text-file.txt")
records = client.sample(10)
```

Sampling more records than remain raises an error and does not change the cache. Run the tests with `python -m unittest`.