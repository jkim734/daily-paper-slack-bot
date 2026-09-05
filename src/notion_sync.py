import os
import re
from typing import List, Optional, Dict, Any
import requests

from .summarizer import PaperSummary
from .config import NotionConfig


class NotionSync:
    NOTION_API_VERSION = "2022-06-28"
    BASE_URL = "https://api.notion.com/v1"

    def __init__(self, api_key: Optional[str], database_id: Optional[str], config: Optional[NotionConfig] = None):
        self.api_key = api_key or os.getenv("NOTION_API_KEY", "")
        self.database_id = database_id or os.getenv("NOTION_DATABASE_ID", "")
        self.config = config or NotionConfig()
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Notion-Version": self.NOTION_API_VERSION,
            "Content-Type": "application/json"
        }

    def is_configured(self) -> bool:
        return bool(self.api_key and self.database_id)

    def resolve_database_id(self) -> Optional[str]:
        """Resolves database ID, automatically detecting an inline child database if a page ID was provided."""
        if not self.is_configured():
            return None
        target_id = self.clean_id(self.database_id)
        # 1. Check if target_id is directly a database
        try:
            res = requests.get(f"{self.BASE_URL}/databases/{target_id}", headers=self.headers, timeout=15)
            if res.status_code == 200:
                return target_id

            # 2. If it is a page containing an inline child database, inspect children
            blocks_res = requests.get(f"{self.BASE_URL}/blocks/{target_id}/children", headers=self.headers, timeout=15)
            if blocks_res.status_code == 200:
                for block in blocks_res.json().get("results", []):
                    if block.get("type") == "child_database":
                        child_id = block.get("id")
                        db_title = block.get("child_database", {}).get("title", "인라인 데이터베이스")
                        print(f"[NotionSync] 💡 페이지 내부에서 인라인 데이터베이스를 자동 감지했습니다: '{db_title}' ({child_id})")
                        self.database_id = child_id
                        return child_id
        except Exception:
            pass
        return target_id

    def test_connection(self) -> bool:
        """Verifies connection to Notion and validates database access."""
        if not self.is_configured():
            print("[NotionSync] NOTION_API_KEY or NOTION_DATABASE_ID is not configured.")
            return False

        db_id = self.resolve_database_id()
        if not db_id:
            print("[NotionSync] ❌ Could not resolve database ID.")
            return False

        url = f"{self.BASE_URL}/databases/{db_id}"
        try:
            res = requests.get(url, headers=self.headers, timeout=15)
            if res.status_code == 200:
                db_data = res.json()
                title = db_data.get("title", [{}])[0].get("plain_text", "Untitled DB")
                print(f"[NotionSync] ✅ Successfully connected to Notion Database: '{title}' ({db_id})")
                return True
            else:
                print(f"[NotionSync] ❌ Notion API error ({res.status_code}): {res.text}")
                return False
        except Exception as e:
            print(f"[NotionSync] ❌ Error connecting to Notion: {e}")
            return False

    def clean_id(self, id_str: str) -> str:
        """Extracts and formats 32-char Notion UUID from any raw ID or full Notion URL."""
        match = re.search(r'([0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12})', id_str.strip())
        if match:
            clean = match.group(1).replace("-", "")
            return f"{clean[0:8]}-{clean[8:12]}-{clean[12:16]}-{clean[16:20]}-{clean[20:32]}"
        return id_str.strip()

    def sync_paper(self, summary: PaperSummary) -> Optional[str]:
        """Creates a page in the Notion database for a paper summary and returns page URL."""
        if not self.is_configured():
            return None

        p = summary.paper
        pub_year = p.published.year if p.published else 2026
        authors_text = ", ".join(p.authors[:3])
        if len(p.authors) > 3:
            authors_text += " et al."

        venue_name = p.venue or ("arXiv" if p.source == "arxiv" else "Preprint")
        # Notion select option max length 100
        venue_name = venue_name[:100]

        # Clean tags (alphanumeric and Korean, remove '#')
        clean_tags = []
        for t in summary.tags:
            t_clean = t.replace("#", "").strip()
            if t_clean and len(t_clean) <= 50:
                clean_tags.append({"name": t_clean})

        # Base properties matching the reference guide
        properties: Dict[str, Any] = {
            "제목": {
                "title": [{"text": {"content": p.clean_title()[:2000]}}]
            },
            "저자": {
                "rich_text": [{"text": {"content": authors_text[:2000]}}]
            },
            "출판연도": {
                "number": pub_year
            },
            "저널": {
                "select": {"name": venue_name}
            },
            "DOI": {
                "url": p.url
            }
        }

        if clean_tags:
            properties["분야/주제"] = {"multi_select": clean_tags[:5]}

        # Status property ("시작 전")
        status_val = self.config.default_status if self.config else "시작 전"
        properties["상태"] = {"status": {"name": status_val}}

        # Build Page Children Blocks (Rich 5-section layout)
        children = []

        def add_h2(text: str):
            children.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]}
            })

        def add_paragraph(text: str):
            if not text:
                return
            # Notion block text chunk limit is 2000 chars
            chunks = [text[i:i+1900] for i in range(0, len(text), 1900)]
            for chunk in chunks:
                children.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]}
                })

        # 1. 한 줄 요약
        if summary.one_line_summary:
            add_h2("💡 한 줄 요약")
            add_paragraph(summary.one_line_summary)

        # 2. 풀려는 문제
        if summary.problem:
            add_h2("🎯 풀려는 문제")
            add_paragraph(summary.problem)

        # 3. 접근 방법
        if summary.method:
            add_h2("⚙️ 접근 방법")
            add_paragraph(summary.method)

        # 4. 핵심 결과
        if summary.result:
            add_h2("📊 핵심 결과")
            add_paragraph(summary.result)

        # 5. 기여점 / 새로운 점
        if summary.contribution:
            add_h2("✨ 기여점 / 새로운 점")
            add_paragraph(summary.contribution)

        # Divider
        children.append({"object": "block", "type": "divider", "divider": {}})

        # 6. 원문 초록 (Abstract)
        add_h2("📄 원문 초록 (Abstract)")
        add_paragraph(p.clean_abstract())

        # Callout Link
        link_text = f"원문 바로가기: {p.url}"
        if p.pdf_url:
            link_text += f" | PDF: {p.pdf_url}"
        children.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{"type": "text", "text": {"content": link_text}}],
                "icon": {"emoji": "🔗"}
            }
        })

        db_id = self.resolve_database_id() or self.clean_id(self.database_id)
        payload = {
            "parent": {"database_id": db_id},
            "properties": properties,
            "children": children
        }

        try:
            res = requests.post(f"{self.BASE_URL}/pages", headers=self.headers, json=payload, timeout=25)
            if res.status_code in (200, 201):
                page_data = res.json()
                page_url = page_data.get("url", "")
                summary.notion_url = page_url
                return page_url
            else:
                # If status property caused error (e.g. user created as select instead of status), retry without status or with select
                if "status" in res.text.lower():
                    properties["상태"] = {"select": {"name": status_val}}
                    payload["properties"] = properties
                    retry_res = requests.post(f"{self.BASE_URL}/pages", headers=self.headers, json=payload, timeout=25)
                    if retry_res.status_code in (200, 201):
                        page_url = retry_res.json().get("url", "")
                        summary.notion_url = page_url
                        return page_url

                print(f"[NotionSync] Failed to insert page for '{p.clean_title()[:40]}...': {res.status_code} - {res.text[:200]}")
                return None
        except Exception as e:
            print(f"[NotionSync] Request exception: {e}")
            return None

    def sync_all(self, summaries: List[PaperSummary]) -> int:
        """Syncs all summaries to Notion and returns count of successfully synced items."""
        if not self.is_configured():
            print("[NotionSync] Skipped Notion sync (NOTION_API_KEY or NOTION_DATABASE_ID not set).")
            return 0

        print(f"[NotionSync] Syncing {len(summaries)} papers to Notion Database...")
        success_count = 0
        for s in summaries:
            url = self.sync_paper(s)
            if url:
                success_count += 1
                print(f"       ✅ Added to Notion: {s.paper.clean_title()[:50]}...")

        print(f"[NotionSync] Completed Notion sync: {success_count}/{len(summaries)} papers added.")
        return success_count
