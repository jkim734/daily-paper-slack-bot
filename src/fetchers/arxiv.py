import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from typing import List, Optional
import requests

from .base import Paper, BaseFetcher
from ..config import ArxivConfig


class ArxivFetcher(BaseFetcher):
    BASE_URL = "https://export.arxiv.org/api/query"
    ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

    def __init__(self, config: ArxivConfig):
        self.config = config

    def _build_search_query(self) -> str:
        parts = []

        # Categories
        if self.config.categories:
            cat_query = " OR ".join(f"cat:{cat.strip()}" for cat in self.config.categories if cat.strip())
            if cat_query:
                parts.append(f"({cat_query})")

        # Keywords
        if self.config.keywords:
            kw_parts = []
            for kw in self.config.keywords:
                kw_clean = kw.strip().replace('"', '')
                if kw_clean:
                    kw_parts.append(f'all:"{kw_clean}"')
            if kw_parts:
                kw_query = " OR ".join(kw_parts)
                parts.append(f"({kw_query})")

        if not parts:
            return "all:ai"

        return " AND ".join(parts)

    def fetch_recent_papers(self, lookback_days: Optional[int] = None) -> List[Paper]:
        days = lookback_days if lookback_days is not None else self.config.lookback_days
        now = datetime.now(timezone.utc)
        since_date = now - timedelta(days=days)

        search_query = self._build_search_query()
        params = {
            "search_query": search_query,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": self.config.max_results,
        }

        headers = {
            "User-Agent": "DailyPaperSlackBot/1.0 (academic research paper monitor; mailto:contact@example.com)"
        }

        try:
            response = requests.get(self.BASE_URL, params=params, headers=headers, timeout=20)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"[ArxivFetcher] Error fetching data from arXiv: {e}")
            return []

        return self._parse_atom_feed(response.text, since_date)

    def _parse_atom_feed(self, xml_text: str, since_date: datetime) -> List[Paper]:
        papers: List[Paper] = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            print(f"[ArxivFetcher] XML Parse error: {e}")
            return []

        for entry in root.findall("atom:entry", self.ATOM_NS):
            id_elem = entry.find("atom:id", self.ATOM_NS)
            title_elem = entry.find("atom:title", self.ATOM_NS)
            summary_elem = entry.find("atom:summary", self.ATOM_NS)
            published_elem = entry.find("atom:published", self.ATOM_NS)

            if id_elem is None or title_elem is None or summary_elem is None or published_elem is None:
                continue

            raw_id = id_elem.text.strip() if id_elem.text else ""
            # Extract standard arXiv ID like 2401.12345
            match = re.search(r"abs/([0-9]+\.[0-9]+|[\w\-]+/[0-9]+)", raw_id)
            arxiv_id = match.group(1) if match else raw_id.split("/")[-1]
            unique_id = f"arxiv:{arxiv_id}"

            # Publication time
            try:
                pub_text = published_elem.text.strip()
                # Typically format: 2025-01-15T18:00:00Z
                published_dt = datetime.fromisoformat(pub_text.replace("Z", "+00:00"))
            except Exception:
                published_dt = datetime.now(timezone.utc)

            # Filter by lookback date (if specified and valid)
            if since_date and published_dt < since_date:
                # arXiv results are sorted descending by submittedDate
                # Still check if we should continue or break
                continue

            title = " ".join(title_elem.text.split())
            abstract = " ".join(summary_elem.text.split())

            # Authors
            authors = []
            for author_elem in entry.findall("atom:author", self.ATOM_NS):
                name_elem = author_elem.find("atom:name", self.ATOM_NS)
                if name_elem is not None and name_elem.text:
                    authors.append(name_elem.text.strip())

            # Categories
            categories = []
            for cat_elem in entry.findall("atom:category", self.ATOM_NS):
                term = cat_elem.attrib.get("term")
                if term:
                    categories.append(term)

            # URLs
            url = f"https://arxiv.org/abs/{arxiv_id}"
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

            paper = Paper(
                id=unique_id,
                title=title,
                authors=authors,
                abstract=abstract,
                published=published_dt,
                url=url,
                pdf_url=pdf_url,
                categories=categories,
                source="arxiv"
            )
            papers.append(paper)

        return papers
