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
        self._schema_cache: Optional[Dict[str, Any]] = None

    def is_configured(self) -> bool:
        return bool(self.api_key and self.database_id)

    def clean_id(self, id_str: str) -> str:
        """Extracts and formats 32-char Notion UUID from any raw ID or full Notion URL."""
        match = re.search(r'([0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12})', id_str.strip())
        if match:
            clean = match.group(1).replace("-", "")
            return f"{clean[0:8]}-{clean[8:12]}-{clean[12:16]}-{clean[16:20]}-{clean[20:32]}"
        return id_str.strip()

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

    def get_database_schema(self) -> Dict[str, Any]:
        """Fetches and caches database properties schema to dynamically adapt to any user column types."""
        if self._schema_cache is not None:
            return self._schema_cache

        db_id = self.resolve_database_id()
        if not db_id:
            return {}

        try:
            res = requests.get(f"{self.BASE_URL}/databases/{db_id}", headers=self.headers, timeout=15)
            if res.status_code == 200:
                self._schema_cache = res.json().get("properties", {})
                return self._schema_cache
            else:
                print(f"[NotionSync] ⚠️ DB 스키마 조회 실패 ({res.status_code}): {res.text[:150]}")
        except Exception as e:
            print(f"[NotionSync] ⚠️ DB 스키마 조회 예외: {e}")

        self._schema_cache = {}
        return self._schema_cache

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
                props = db_data.get("properties", {})
                print(f"[NotionSync] 📋 Detected columns: {', '.join(props.keys())}")
                return True
            else:
                print(f"[NotionSync] ❌ Notion API error ({res.status_code}): {res.text}")
                return False
        except Exception as e:
            print(f"[NotionSync] ❌ Error connecting to Notion: {e}")
            return False

    def _build_properties(self, summary: PaperSummary, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Dynamically creates Notion page properties based on actual column types in user database."""
        p = summary.paper
        pub_year = p.published.year if p.published else 2026
        authors_text = ", ".join(p.authors[:3])
        if len(p.authors) > 3:
            authors_text += " et al."

        venue_name = p.venue or ("arXiv" if p.source == "arxiv" else "Preprint")
        if p.scites and p.scites > 0:
            venue_name = f"{venue_name} (🔥 SciRate {p.scites})"
        venue_name = venue_name[:100]

        clean_tags = []
        for t in summary.tags:
            t_clean = t.replace("#", "").strip()
            if t_clean and len(t_clean) <= 50:
                clean_tags.append({"name": t_clean})

        properties: Dict[str, Any] = {}

        # 1. Title property (find column of type 'title')
        title_prop_name = None
        for name, info in schema.items():
            if info.get("type") == "title":
                title_prop_name = name
                break
        title_prop_name = title_prop_name or "제목"
        properties[title_prop_name] = {
            "title": [{"text": {"content": p.clean_title()[:2000]}}]
        }

        # Helper to match property name case-insensitively or by alias
        def find_prop(aliases: List[str]) -> Optional[tuple[str, Dict[str, Any]]]:
            for alias in aliases:
                for name, info in schema.items():
                    if name.lower() == alias.lower():
                        return name, info
            return None

        # 2. 저자 (Authors)
        author_match = find_prop(["저자", "Author", "Authors"])
        if author_match:
            name, info = author_match
            if info.get("type") == "rich_text":
                properties[name] = {"rich_text": [{"text": {"content": authors_text[:2000]}}]}

        # 3. 출판연도 (Year)
        year_match = find_prop(["출판연도", "Year", "연도", "Publication Year"])
        if year_match:
            name, info = year_match
            p_type = info.get("type")
            if p_type == "number":
                properties[name] = {"number": pub_year}
            elif p_type == "rich_text":
                properties[name] = {"rich_text": [{"text": {"content": str(pub_year)}}]}
            elif p_type == "select":
                properties[name] = {"select": {"name": str(pub_year)}}

        # 4. 저널 (Journal / Venue)
        journal_match = find_prop(["저널", "Journal", "Venue", "학술지"])
        if journal_match:
            name, info = journal_match
            p_type = info.get("type")
            if p_type == "rich_text":
                properties[name] = {"rich_text": [{"text": {"content": venue_name}}]}
            elif p_type == "select":
                properties[name] = {"select": {"name": venue_name}}

        # 5. DOI / URL
        doi_match = find_prop(["DOI", "URL", "링크", "Link"])
        if doi_match:
            name, info = doi_match
            p_type = info.get("type")
            if p_type == "url":
                properties[name] = {"url": p.url}
            elif p_type == "rich_text":
                properties[name] = {"rich_text": [{"text": {"content": p.url}}]}

        # 6. 분야/주제 (Category / Tags)
        tag_match = find_prop(["분야/주제", "태그", "주제", "Tags", "Category"])
        if tag_match and clean_tags:
            name, info = tag_match
            p_type = info.get("type")
            if p_type == "multi_select":
                properties[name] = {"multi_select": clean_tags[:5]}
            elif p_type == "rich_text":
                properties[name] = {"rich_text": [{"text": {"content": ", ".join(t["name"] for t in clean_tags[:5])}}]}

        # 7. 상태 (Status)
        status_match = find_prop(["상태", "Status"])
        if status_match:
            name, info = status_match
            p_type = info.get("type")
            if p_type == "status":
                status_options = info.get("status", {}).get("options", [])
                option_names = [opt.get("name") for opt in status_options if opt.get("name")]
                # Priority: configured status -> "읽을 예정" -> "시작 전" -> first option
                target_status = self.config.default_status if self.config else "읽을 예정"
                if target_status not in option_names:
                    # fallback to first option or "읽을 예정"
                    for candidate in ["읽을 예정", "시작 전", "To-do", "Not started"]:
                        if candidate in option_names:
                            target_status = candidate
                            break
                    else:
                        target_status = option_names[0] if option_names else "읽을 예정"
                properties[name] = {"status": {"name": target_status}}
            elif p_type == "select":
                select_options = [opt.get("name") for opt in info.get("select", {}).get("options", [])]
                target_status = self.config.default_status if self.config else "읽을 예정"
                if select_options and target_status not in select_options:
                    target_status = select_options[0]
                properties[name] = {"select": {"name": target_status}}

        return properties

    def sync_paper(self, summary: PaperSummary) -> Optional[str]:
        """Creates a page in the Notion database for a paper summary and returns page URL."""
        if not self.is_configured():
            return None

        p = summary.paper
        schema = self.get_database_schema()
        properties = self._build_properties(summary, schema)

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

        # 2. 핵심 용어 사전 (쉬운 개념 풀이)
        if summary.key_terms:
            add_h2("📖 핵심 용어 사전")
            for kt in summary.key_terms:
                if isinstance(kt, dict):
                    t_name = kt.get("term", "").strip()
                    t_def = kt.get("definition", "").strip()
                    if t_name and t_def:
                        add_paragraph(f"▫️ **{t_name}**: {t_def}")
                elif isinstance(kt, str) and kt.strip():
                    add_paragraph(f"▫️ {kt.strip()}")

        # 3. 풀려는 문제
        if summary.problem:
            add_h2("🎯 풀려는 문제")
            add_paragraph(summary.problem)

        # 4. 접근 방법
        if summary.method:
            add_h2("⚙️ 접근 방법")
            add_paragraph(summary.method)

        # 5. 핵심 성과
        if summary.result:
            add_h2("📊 핵심 성과")
            add_paragraph(summary.result)

        # 6. 의의 및 기여점
        if summary.contribution:
            add_h2("✨ 의의 및 기여점")
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
        if p.scirate_url:
            scite_badge = f" ({p.scites} Scites)" if p.scites is not None else ""
            link_text += f" | 🔥 SciRate 토론: {p.scirate_url}{scite_badge}"
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
                err_text = res.text
                print(f"[NotionSync] ⚠️ Failed initial page insert: {res.status_code} - {err_text[:200]}")
                # Fallback: Retry with minimal safe properties (title only) to ensure user never loses content
                title_key = next((k for k, v in properties.items() if "title" in v), "제목")
                fallback_payload = {
                    "parent": {"database_id": db_id},
                    "properties": {title_key: properties[title_key]},
                    "children": children
                }
                retry_res = requests.post(f"{self.BASE_URL}/pages", headers=self.headers, json=fallback_payload, timeout=25)
                if retry_res.status_code in (200, 201):
                    page_url = retry_res.json().get("url", "")
                    summary.notion_url = page_url
                    print(f"[NotionSync] ✅ Page created via fallback for '{p.clean_title()[:40]}...'")
                    return page_url
                else:
                    print(f"[NotionSync] ❌ Fallback also failed: {retry_res.status_code} - {retry_res.text[:200]}")
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
