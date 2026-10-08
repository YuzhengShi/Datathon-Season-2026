import dataclasses
import tempfile
import unittest
from pathlib import Path

from navigator.config import derive_runtime
from navigator.ingestion.adapters import registry
from navigator.ingestion.extractors import ExtractorUnavailable, LLMExtractor, select_adapters
from navigator.ingestion.memory_repo import MemoryRepository
from navigator.services import live
from tests.support import AS_OF
from tests.test_live_pipeline import Router

ROOT = Path(__file__).resolve().parent.parent


class ExtractionModeTests(unittest.TestCase):
    def test_deterministic_is_the_default_and_keeps_every_adapter(self):
        adapters = registry()
        self.assertEqual(select_adapters("deterministic", adapters), adapters)

    def test_curated_mode_runs_only_curated_adapters(self):
        self.assertEqual(set(select_adapters("curated", registry())), {"curated_awards", "curated_channel"})

    def test_llm_mode_is_an_explicit_error_never_a_silent_fallback(self):
        with self.assertRaises(ExtractorUnavailable) as caught:
            select_adapters("llm", registry())
        self.assertIn("not implemented", str(caught.exception))
        with self.assertRaises(ExtractorUnavailable):
            LLMExtractor().parse([], None, None)  # no stub that "succeeds"
        with self.assertRaises(ExtractorUnavailable):
            select_adapters("telepathy", registry())

    def test_live_pipeline_refuses_llm_mode_before_any_network_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt = derive_runtime({"DATA_DIR": tmp, "SOURCE_CONFIG": str(ROOT / "sources.yaml"), "EXTRACTION_MODE": "llm",
                                 "OPENAI_API_KEY": "sk-unused", "OPENAI_MODEL": "m"}, "live")
            router = Router()
            with self.assertRaises(ExtractorUnavailable):
                live.run_live_pipeline(MemoryRepository(), rt, now=AS_OF, limit=30, max_pages=50, resume=False, refresh=False,
                                       fetcher=live.build_fetcher(rt, router))
            self.assertEqual(router.calls, [])  # nothing was fetched

    def test_curated_mode_skips_sources_that_need_other_adapters(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = derive_runtime({"DATA_DIR": tmp, "SOURCE_CONFIG": str(ROOT / "sources.yaml"), "FETCH_RETRIES": "0",
                                   "FETCH_MIN_INTERVAL_SECONDS": "0"}, "live")
            rt = dataclasses.replace(base, extraction_mode="curated")
            result = live.run_live_pipeline(MemoryRepository(), rt, now=AS_OF, limit=30, max_pages=50, resume=False,
                                            refresh=False, fetcher=live.build_fetcher(rt, Router()))
            self.assertEqual(result["real_opportunities"], 0)  # no curated mapping exists, so nothing is invented
            manifest = (Path(tmp) / "runs" / f"{result['run_id']}.json").read_text(encoding="utf-8")
            self.assertIn("available in extraction mode", manifest)
            self.assertIn("no curated mapping", manifest)


if __name__ == "__main__":
    unittest.main()
