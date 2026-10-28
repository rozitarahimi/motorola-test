from __future__ import annotations

import base64
import codecs
import http.client
import json
import random
import threading
from dataclasses import dataclass
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable, TextIO


@dataclass(frozen=True)
class SampleRecord:
	"""A sampled record encoded as bytes, with its source encoding."""

	data: bytes
	encoding: str


class SampleStore:
	"""Thread-safe storage for newline-delimited text records."""

	def __init__(self) -> None:
		self._lines: list[tuple[str, str]] = []
		self._lock = threading.Lock()

	def load(
		self, source: str | Path | TextIO | Iterable[str], encoding: str = "utf-8"
	) -> int:
		"""Append text lines, retaining the encoding used to read them."""
		encoding = codecs.lookup(encoding).name
		if isinstance(source, (str, Path)):
			with Path(source).open("r", encoding=encoding, newline=None) as file:
				return self._append_lines(file, encoding)
		return self._append_lines(source, encoding)

	def _append_lines(self, lines: Iterable[str], encoding: str) -> int:
		count = 0
		for raw_line in lines:
			line = raw_line.removesuffix("\n").removesuffix("\r")
			with self._lock:
				self._lines.append((line, encoding))
			count += 1
		return count

	def sample(self, count: int) -> list[SampleRecord]:
		"""Return and remove random lines encoded with their original encodings."""
		if not isinstance(count, int):
			raise TypeError("count must be an integer")
		if count < 0:
			raise ValueError("count must not be negative")

		with self._lock:
			if count > len(self._lines):
				raise ValueError("not enough lines available")

			indices = random.sample(range(len(self._lines)), count)
			selected = []
			for index in indices:
				line, encoding = self._lines[index]
				selected.append(SampleRecord(line.encode(encoding), encoding))
			for index in sorted(indices, reverse=True):
				last_line = self._lines.pop()
				if index < len(self._lines):
					self._lines[index] = last_line
			return selected


GLOBAL_STORE = SampleStore()


class SampleRequestHandler(BaseHTTPRequestHandler):
	store: SampleStore

	def __init__(self, *args: object, store: SampleStore, **kwargs: object) -> None:
		self.store = store
		super().__init__(*args, **kwargs)

	def do_POST(self) -> None:
		try:
			content_length = int(self.headers.get("Content-Length", ""))
			if content_length < 0:
				raise ValueError
		except ValueError:
			self._send_json(400, {"error": "a valid Content-Length is required"})
			return

		if self.path == "/load":
			try:
				encoding = self.headers.get_content_charset() or "utf-8"
				loaded = self.store.load(
					self._request_lines(content_length, encoding), encoding=encoding
				)
			except (LookupError, UnicodeDecodeError, OSError, ValueError) as error:
				self._send_json(400, {"error": str(error)})
				return
			self._send_json(200, {"loaded": loaded})
			return

		if self.path == "/sample":
			try:
				body = self.rfile.read(content_length)
				payload = json.loads(body)
				if not isinstance(payload, dict) or "count" not in payload:
					raise ValueError("request must contain an integer count")
				sampled = self.store.sample(payload["count"])
			except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as error:
				status = 409 if str(error) == "not enough lines available" else 400
				self._send_json(status, {"error": str(error)})
				return
			self._send_json(
				200,
				{
					"lines": [
						{
							"data": base64.b64encode(record.data).decode("ascii"),
							"encoding": record.encoding,
						}
						for record in sampled
					]
				},
			)
			return

		self._send_json(404, {"error": "unknown endpoint"})

	def _request_lines(self, content_length: int, encoding: str) -> Iterable[str]:
		decoder = codecs.getincrementaldecoder(encoding)()
		remaining = content_length
		buffered = ""

		while remaining:
			chunk = self.rfile.read(min(65536, remaining))
			if not chunk:
				raise ValueError("request body ended unexpectedly")
			remaining -= len(chunk)
			buffered += decoder.decode(chunk)
			while "\n" in buffered:
				line, buffered = buffered.split("\n", 1)
				yield line.removesuffix("\r")

		buffered += decoder.decode(b"", final=True)
		if buffered:
			yield buffered.removesuffix("\r")

	def _send_json(self, status: int, payload: dict[str, object]) -> None:
		body = json.dumps(payload).encode("utf-8")
		self.send_response(status)
		self.send_header("Content-Type", "application/json; charset=utf-8")
		self.send_header("Content-Length", str(len(body)))
		self.end_headers()
		self.wfile.write(body)

	def log_message(self, format: str, *args: object) -> None:
		return


class SampleHTTPServer(ThreadingHTTPServer):
	daemon_threads = True
	allow_reuse_address = True


def create_server(
	host: str = "127.0.0.1", port: int = 8765, store: SampleStore = GLOBAL_STORE
) -> SampleHTTPServer:
	handler = partial(SampleRequestHandler, store=store)
	return SampleHTTPServer((host, port), handler)


class SampleClient:
	def __init__(self, host: str = "127.0.0.1", port: int = 8765, timeout: float = 30) -> None:
		self.host = host
		self.port = port
		self.timeout = timeout

	def load(self, file_path: str | Path, encoding: str = "utf-8") -> int:
		"""Stream a text file to the server and return its line count."""
		path = Path(file_path)
		with path.open("rb") as file:
			content_length = path.stat().st_size
			response = self._request(
				"/load",
				file,
				{
					"Content-Type": f"text/plain; charset={codecs.lookup(encoding).name}",
					"Content-Length": str(content_length),
				},
			)
		return int(response["loaded"])

	def sample(self, count: int) -> list[SampleRecord]:
		body = json.dumps({"count": count}).encode("utf-8")
		response = self._request(
			"/sample",
			body,
			{"Content-Type": "application/json", "Content-Length": str(len(body))},
		)
		lines = response.get("lines")
		if not isinstance(lines, list):
			raise RuntimeError("server returned an invalid sample response")

		samples: list[SampleRecord] = []
		for line in lines:
			if (
				not isinstance(line, dict)
				or not isinstance(line.get("data"), str)
				or not isinstance(line.get("encoding"), str)
			):
				raise RuntimeError("server returned an invalid sample record")
			samples.append(
				SampleRecord(
					base64.b64decode(line["data"], validate=True),
					line["encoding"],
				)
			)
		return samples

	def _request(
		self, path: str, body: object, headers: dict[str, str]
	) -> dict[str, object]:
		connection = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
		try:
			connection.request("POST", path, body=body, headers=headers)
			response = connection.getresponse()
			payload = json.loads(response.read())
			if response.status >= 400:
				raise RuntimeError(payload.get("error", "server request failed"))
			return payload
		finally:
			connection.close()


if __name__ == "__main__":
	server = create_server()
	print(f"Sampling server listening on http://{server.server_address[0]}:{server.server_address[1]}")
	try:
		server.serve_forever()
	except KeyboardInterrupt:
		pass
	finally:
		server.server_close()
