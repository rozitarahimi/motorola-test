import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from server import SampleClient, SampleStore, create_server


class SampleStoreTests(unittest.TestCase):
    def test_load_and_sample_test_jsonl(self) -> None:
        fixture = Path(__file__).with_name("test.jsonl")
        expected_lines = fixture.read_text(encoding="utf-8").splitlines()
        store = SampleStore()

        self.assertGreater(len(expected_lines), 0)
        self.assertEqual(store.load(fixture), len(expected_lines))

        samples = store.sample(len(expected_lines))
        self.assertCountEqual(
            [(sample.data, sample.encoding) for sample in samples],
            [(line.encode("utf-8"), "utf-8") for line in expected_lines],
        )
        self.assertEqual(store.sample(0), [])

    def test_load_and_sample_remove_lines(self) -> None:
        store = SampleStore()
        with tempfile.TemporaryDirectory() as directory:
            text_file = Path(directory) / "records.txt"
            text_file.write_text("first\nsecond\nthird\n", encoding="utf-8")

            self.assertEqual(store.load(text_file), 3)

        samples = store.sample(3)
        self.assertCountEqual(
            [sample.data.decode(sample.encoding) for sample in samples],
            ["first", "second", "third"],
        )
        self.assertEqual(store.sample(0), [])
        with self.assertRaisesRegex(ValueError, "not enough lines"):
            store.sample(1)

    def test_load_non_utf8_file(self) -> None:
        store = SampleStore()
        with tempfile.TemporaryDirectory() as directory:
            text_file = Path(directory) / "records.txt"
            text_file.write_text("café\nniño\n", encoding="latin-1")

            self.assertEqual(store.load(text_file, encoding="latin-1"), 2)

        samples = store.sample(2)
        self.assertCountEqual(
            [(sample.data, sample.encoding) for sample in samples],
            [(b"caf\xe9", "iso8859-1"), (b"ni\xf1o", "iso8859-1")],
        )

    def test_sample_retains_each_record_encoding(self) -> None:
        store = SampleStore()
        store.load(["café\n"], encoding="cp1252")
        store.load(["café\n"], encoding="utf-8")

        samples = store.sample(2)
        self.assertCountEqual(
            [(sample.data, sample.encoding) for sample in samples],
            [(b"caf\xe9", "cp1252"), ("café".encode("utf-8"), "utf-8")],
        )

    def test_concurrent_samples_never_return_same_record(self) -> None:
        store = SampleStore()
        store.load([f"record-{index}\n" for index in range(100)])

        with ThreadPoolExecutor(max_workers=16) as executor:
            results = list(executor.map(lambda _: store.sample(1)[0], range(100)))

        self.assertEqual(len(set(results)), 100)

    def test_http_client_load_and_sample(self) -> None:
        store = SampleStore()
        server = create_server("127.0.0.1", 0, store)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = SampleClient(*server.server_address)
            with tempfile.TemporaryDirectory() as directory:
                text_file = Path(directory) / "records.txt"
                text_file.write_text("one\ntwo", encoding="utf-8")

                self.assertEqual(client.load(text_file), 2)
                self.assertCountEqual(
                    [sample.data.decode(sample.encoding) for sample in client.sample(2)],
                    ["one", "two"],
                )

                text_file.write_text("café\n€uro", encoding="cp1252")
                self.assertEqual(client.load(text_file, encoding="cp1252"), 2)
                self.assertCountEqual(
                    [(sample.data, sample.encoding) for sample in client.sample(2)],
                    [(b"caf\xe9", "cp1252"), (b"\x80uro", "cp1252")],
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()