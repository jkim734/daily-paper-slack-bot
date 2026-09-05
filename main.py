import argparse
import sys
from typing import List

from src.config import load_config
from src.db import HistoryDB
from src.fetchers.arxiv import ArxivFetcher
from src.fetchers.pubmed import PubmedFetcher
from src.fetchers.journals import JournalFetcher
from src.fetchers.base import Paper
from src.summarizer import Summarizer
from src.notifier import SlackNotifier
from src.notion_sync import NotionSync


def parse_args():
    parser = argparse.ArgumentParser(description="Daily Research Paper Slack Bot")
    parser.add_argument("--config", type=str, default=None, help="Path to config.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Preview summaries without sending to Slack or updating DB")
    parser.add_argument("--test-slack", action="store_true", help="Send a test message to Slack and exit")
    parser.add_argument("--test-notion", action="store_true", help="Test connection to Notion Database and exit")
    parser.add_argument("--days", type=int, default=None, help="Override lookback days")
    parser.add_argument("--limit", type=int, default=None, help="Override maximum papers to send")
    parser.add_argument("--min", type=int, default=None, help="Override minimum papers to send")
    parser.add_argument("--force", action="store_true", help="Include papers even if already sent in DB")
    return parser.parse_args()


def main():
    args = parse_args()
    config = load_config(args.config)

    # Override limits if passed
    if args.limit is not None:
        config.summarizer.max_k = args.limit
        config.summarizer.top_k = args.limit
    if args.min is not None:
        config.summarizer.min_k = args.min

    min_k = config.summarizer.min_k
    max_k = config.summarizer.max_k

    notifier = SlackNotifier(config.slack_webhook_url, config.slack)
    notion_sync = NotionSync(config.notion_api_key, config.notion.database_id, config.notion)

    # 1. Connection Tests
    if args.test_slack:
        print("[Main] Sending test notification to Slack...")
        success = notifier.send_test_message()
        if success:
            print("✅ Test message successfully sent to Slack!")
            sys.exit(0)
        else:
            print("❌ Failed to send test message to Slack. Check your SLACK_WEBHOOK_URL in .env.")
            sys.exit(1)

    if args.test_notion:
        print("[Main] Testing connection to Notion Database...")
        success = notion_sync.test_connection()
        if success:
            sys.exit(0)
        else:
            print("❌ Failed to connect to Notion. Check NOTION_API_KEY and NOTION_DATABASE_ID in .env.")
            sys.exit(1)

    print("=" * 60)
    print("🚀 Starting Daily Research Paper Bot")
    print(f"Sources: {config.sources}")
    print(f"Summarizer: {config.summarizer.provider} ({config.summarizer.model})")
    print(f"Target Delivery: {min_k} ~ {max_k} papers per day")
    print(f"Dry Run: {args.dry_run}")
    print("=" * 60)

    db = HistoryDB(config.storage.db_path)

    # 2. Fetch papers from all active sources
    all_papers: List[Paper] = []
    days = args.days

    arxiv_fetcher = None
    if "arxiv" in config.sources:
        print(f"[Main] Fetching arXiv papers (categories: {config.arxiv.categories})...")
        arxiv_fetcher = ArxivFetcher(config.arxiv)
        arxiv_papers = arxiv_fetcher.fetch_recent_papers(lookback_days=days)
        print(f"       Found {len(arxiv_papers)} papers from arXiv.")
        all_papers.extend(arxiv_papers)

    if "pubmed" in config.sources and config.pubmed.query:
        print(f"[Main] Fetching PubMed papers (query: {config.pubmed.query})...")
        pubmed_fetcher = PubmedFetcher(config.pubmed)
        pubmed_papers = pubmed_fetcher.fetch_recent_papers(lookback_days=days)
        print(f"       Found {len(pubmed_papers)} papers from PubMed.")
        all_papers.extend(pubmed_papers)

    if "journals" in config.sources and config.journals.venues:
        print(f"[Main] Fetching peer-reviewed journal papers ({len(config.journals.venues)} venues: Nature, PRL, Quantum, etc.)...")
        journal_fetcher = JournalFetcher(config.journals)
        journal_papers = journal_fetcher.fetch_recent_papers(lookback_days=days)
        print(f"       Found {len(journal_papers)} papers from prestigious journals.")
        all_papers.extend(journal_papers)

    if not all_papers:
        print("[Main] No papers found for the specified period and criteria.")
        return

    # 3. Filter unsent papers
    if not args.force:
        candidate_papers = [p for p in all_papers if not db.is_paper_sent(p.id)]
        print(f"[Main] {len(candidate_papers)} new (unsent) papers out of {len(all_papers)} total candidates.")
    else:
        print("[Main] Force flag active: evaluating all retrieved papers.")
        candidate_papers = all_papers

    # If new candidates are fewer than min_k (e.g. weekends), try expanding lookback window
    if len(candidate_papers) < min_k and days is None and arxiv_fetcher is not None:
        print(f"[Main] New candidates ({len(candidate_papers)}) below minimum target ({min_k}). Expanding search window to 6 days...")
        expanded_papers = arxiv_fetcher.fetch_recent_papers(lookback_days=6)
        existing_ids = {p.id for p in all_papers}
        for ep in expanded_papers:
            if ep.id not in existing_ids:
                all_papers.append(ep)
        if not args.force:
            candidate_papers = [p for p in all_papers if not db.is_paper_sent(p.id)]
        else:
            candidate_papers = all_papers
        print(f"[Main] Total candidates after expansion: {len(candidate_papers)}.")

    if not candidate_papers:
        print("[Main] All retrieved papers were already sent previously. Nothing new to send.")
        return

    # 4. Summarize and rank using LLM
    print(f"[Main] Analyzing and selecting {min_k}~{max_k} papers with {config.summarizer.provider}...")
    summarizer = Summarizer(
        config=config.summarizer,
        gemini_api_key=config.gemini_api_key,
        openai_api_key=config.openai_api_key
    )

    summaries = summarizer.summarize_and_rank(candidate_papers)
    print(f"[Main] Generated {len(summaries)} summaries.")

    if not summaries:
        print("[Main] No summaries produced.")
        return

    # 5. Sync to Notion Database (if configured)
    if config.notion.enabled and not args.dry_run:
        if notion_sync.is_configured():
            notion_sync.sync_all(summaries)
        else:
            print("[Main] Notion sync skipped: NOTION_API_KEY or NOTION_DATABASE_ID not set.")
    elif config.notion.enabled and args.dry_run:
        print(f"[Main] (Dry Run) Would sync {len(summaries)} papers to Notion Database.")

    # 6. Send to Slack or Preview
    success = notifier.send_summaries(summaries, dry_run=args.dry_run)

    # 7. Mark as sent in SQLite DB
    if success and not args.dry_run:
        for item in summaries:
            db.mark_paper_sent(
                paper_id=item.paper.id,
                title=item.paper.clean_title(),
                source=item.paper.source,
                summary=item.one_line_summary
            )
        print(f"[Main] Successfully recorded {len(summaries)} papers into history DB ({config.storage.db_path}).")
    elif args.dry_run:
        print("[Main] Dry run complete. History DB was not modified.")


if __name__ == "__main__":
    main()
