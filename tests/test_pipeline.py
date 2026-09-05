import unittest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone

from src.db import HistoryDB
from src.fetchers.base import Paper
from src.summarizer import PaperSummary
from src.notifier import SlackNotifier
from src.config import SlackConfig


class TestPaperBot(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_history.db"
        self.db = HistoryDB(str(self.db_path))

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_db_mark_and_check(self):
        paper_id = "arxiv:2401.99999"
        self.assertFalse(self.db.is_paper_sent(paper_id))

        self.db.mark_paper_sent(paper_id, "Sample Title", "arxiv", "Sample summary")
        self.assertTrue(self.db.is_paper_sent(paper_id))

    def test_db_filter_unsent(self):
        papers = [
            {"id": "arxiv:001", "title": "Paper 1"},
            {"id": "arxiv:002", "title": "Paper 2"},
            {"id": "arxiv:003", "title": "Paper 3"},
        ]
        self.db.mark_paper_sent("arxiv:002", "Paper 2", "arxiv")

        unsent = self.db.filter_unsent_papers(papers)
        self.assertEqual(len(unsent), 2)
        unsent_ids = [p["id"] for p in unsent]
        self.assertIn("arxiv:001", unsent_ids)
        self.assertIn("arxiv:003", unsent_ids)
        self.assertNotIn("arxiv:002", unsent_ids)

    def test_slack_formatter(self):
        cfg = SlackConfig()
        notifier = SlackNotifier(None, cfg)

        paper = Paper(
            id="arxiv:2401.00001",
            title="Reasoning in LLMs",
            authors=["Alice Smith", "Bob Jones"],
            abstract="This paper explores reasoning capabilities in modern LLMs.",
            published=datetime.now(timezone.utc),
            url="https://arxiv.org/abs/2401.00001",
            pdf_url="https://arxiv.org/pdf/2401.00001.pdf",
            categories=["cs.AI", "cs.CL"]
        )

        summary = PaperSummary(
            paper=paper,
            relevance_score=9,
            one_line_summary="LLM의 추론 성능을 비약적으로 개선하는 새로운 기법 제안",
            problem="복잡한 다단계 추론 시 오류가 누적됨",
            method="사고 사슬 최적화 기법 적용",
            result="벤치마크 15% 성능 향상",
            contribution="추론 연산 비용 절감 및 정확도 제고",
            key_terms=[
                {"term": "사고 사슬(Chain-of-Thought)", "definition": "답을 바로 내지 않고 사람처럼 중간 생각 과정을 단계별로 거쳐 추론하는 기법"}
            ],
            key_points=["연구 배경: 추론 한계", "핵심 기법: CoT 최적화", "주요 결과: 15% 성능 향상"],
            tags=["#LLM", "#Reasoning"]
        )

        blocks = notifier.format_blocks([summary], date_str="2026-09-05")
        self.assertTrue(len(blocks) > 0)
        # Check header
        self.assertEqual(blocks[0]["type"], "header")
        # Check text contains title
        block_text = str(blocks)
        self.assertIn("Reasoning in LLMs", block_text)
        self.assertIn("LLM의 추론 성능을 비약적으로 개선", block_text)
        self.assertIn("사고 사슬(Chain-of-Thought)", block_text)

    def test_notion_clean_id(self):
        from src.notion_sync import NotionSync
        sync = NotionSync("key", "db")
        # Test dash insertion for 32-char hex string
        raw_id = "3b85ca12c7ac805fb70bcb9eaff150e7"
        cleaned = sync.clean_id(raw_id)
        self.assertEqual(cleaned, "3b85ca12-c7ac-805f-b70b-cb9eaff150e7")
        # Test full URL extraction
        url_id = "https://www.notion.so/myworkspace/3b85ca12c7ac805fb70bcb9eaff150e7?v=123"
        self.assertEqual(sync.clean_id(url_id), "3b85ca12-c7ac-805f-b70b-cb9eaff150e7")


    def test_scirate_parser(self):
        from src.fetchers.scirate import ScirateFetcher, ScirateConfig
        fetcher = ScirateFetcher(ScirateConfig(min_scites=2))
        sample_html = '''
        <ul class="papers">
          <li class="paper tex2jax">
            <button class="btn btn-default count">7</button>
            <div class="title"><a href="/arxiv/2609.12345v1">Fault-Tolerant Quantum Computation with Magic States</a></div>
            <div class="authors">
              <a href="/search?q=au:Alice_A">Alice A</a>, <a href="/search?q=au:Bob_B">Bob B</a>
            </div>
            <div class="abstract">A new approach to magic state distillation in surface codes.</div>
            <div class="uid">Sep 04 2026</div>
            <div class="categories"><a href="/arxiv/quant-ph">quant-ph</a></div>
          </li>
          <li class="paper tex2jax">
            <button class="btn btn-default count">1</button>
            <div class="title"><a href="/arxiv/2609.99999">Low Scites Paper</a></div>
            <div class="authors"><a href="/search?q=au:Charlie">Charlie</a></div>
            <div class="abstract">Not enough scites.</div>
          </li>
        </ul>
        '''
        papers = fetcher._parse_html(sample_html)
        self.assertEqual(len(papers), 2)
        p1 = papers[0]
        self.assertEqual(p1.id, "arxiv:2609.12345")
        self.assertEqual(p1.title, "Fault-Tolerant Quantum Computation with Magic States")
        self.assertEqual(p1.scites, 7)
        self.assertEqual(p1.scirate_url, "https://scirate.com/arxiv/2609.12345")
        self.assertIn("Alice A", p1.authors)
        self.assertIn("quant-ph", p1.categories)


if __name__ == "__main__":
    unittest.main()

