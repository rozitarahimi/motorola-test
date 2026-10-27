import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from server import SampleClient, SampleStore, create_server


class SampleStoreTests(unittest.TestCase):
    def test_load_and_sample_remove_lines(self) -> None:
        store = SampleStore()
        with tempfile.TemporaryDirectory() as directory:
            text_file = Path(directory) / "records.txt"
            text_file.write_text("first\nsecond\nthird\n", encoding="utf-8")

            self.assertEqual(store.load(text_file), 3)

        samples = store.sample(3)
        self.assertCountEqual(samples, ["first", "second", "third"])
        self.assertEqual(store.sample(0), [])
        with self.assertRaisesRegex(ValueError, "not enough lines"):
            store.sample(1)

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
                self.assertCountEqual(client.sample(2), ["one", "two"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()