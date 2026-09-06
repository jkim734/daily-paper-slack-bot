from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict
import requests

from .base import Paper, BaseFetcher
from ..config import JournalConfig


# Mapping of OpenAlex Source IDs for user-specified prestigious journals
JOURNAL_SOURCE_IDS: Dict[str, str] = {
    "Nature": "S137773608",
    "Science": "S3880285",
    "Nature Physics": "S156274416",
    "Nature Electronics": "S4210239724",
    "Physical Review Letters": "S24807848",
    "Physical Review A": "S164566984",
    "Physical Review Research": "S4210240247",
    "Physical Review X": "S137042341",
    "Quantum": "S4210226432",
    "IEEE Transactions on Quantum Engineering": "S4210182817",
    "ACM Transactions on Quantum Computing": "S4210170170",
    "Quantum Information Processing": "S92819544",
    "Quantum Information & Computation": "S41034432",
    "npj Quantum Information": "S2738600312",
    "International Journal of Quantum Information": "S9756463",
}


class JournalFetcher(BaseFetcher):
    BASE_URL = "https://api.openalex.org/works"

    def __init__(self, config: JournalConfig):
        self.config = config

    def _reconstruct_abstract(self, inverted_index: Optional[dict]) -> str:
        if not inverted_index:
            return "No abstract available."
        try:
            word_list = []
            for word, pos_list in inverted_index.items():
                for pos in pos_list:
                    word_list.append((pos, word))
            word_list.sort(key=lambda x: x[0])
            return " ".join(item[1] for item in word_list)
        except Exception:
            return "No abstract available."

    def _fetch_abstract_from_arxiv(self, title: str) -> Optional[str]:
        """Attempts to find preprint abstract on arXiv when journal metadata lacks open abstract."""
        try:
            import xml.etree.ElementTree as ET
            import re
            clean_t = re.sub(r'[^a-zA-Z0-9\s]', ' ', title).strip()
            if len(clean_t) < 10:
                return None
            q = f'ti:"{clean_t[:100]}"'
            url = f"https://export.arxiv.org/api/query?search_query={requests.utils.quote(q)}&max_results=1"
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                root = ET.fromstring(r.text)
                entry = root.find("{http://www.w3.org/2005/Atom}entry")
                if entry is not None:
                    summary = entry.find("{http://www.w3.org/2005/Atom}summary")
                    if summary is not None and summary.text and len(summary.text.strip()) > 80:
                        return " ".join(summary.text.split())
        except Exception:
            pass
        return None

    def fetch_recent_papers(self, lookback_days: Optional[int] = None) -> List[Paper]:
        days = lookback_days if lookback_days is not None else self.config.lookback_days
        now = datetime.now(timezone.utc)
        since_date = (now - timedelta(days=days)).strftime("%Y-%m-%d")

        # Determine target source IDs
        target_ids = []
        if self.config.venues:
            for v in self.config.venues:
                if v in JOURNAL_SOURCE_IDS:
                    target_ids.append(JOURNAL_SOURCE_IDS[v])
        if not target_ids:
            target_ids = list(JOURNAL_SOURCE_IDS.values())

        sources_filter = "|".join(target_ids)

        # Build keywords search
        keywords = self.config.keywords or [
            "quantum computing", "quantum machine learning", "quantum algorithm", "quantum error correction"
        ]
        search_terms = " OR ".join(f'"{kw.strip()}"' for kw in keywords if kw.strip())

        params = {
            "filter": f"primary_location.source.id:{sources_filter},from_publication_date:{since_date},default.search:{search_terms}",
            "per_page": min(self.config.max_results, 50),
            "sort": "publication_date:desc",
        }

        headers = {
            "User-Agent": "DailyQuantumPaperSlackBot/1.0 (academic research monitor; mailto:contact@example.com)"
        }
        params["mailto"] = "academic-paper-bot@users.noreply.github.com"

        import time
        max_retries = 3
        data = None
        for attempt in range(1, max_retries + 1):
            try:
                response = requests.get(self.BASE_URL, params=params, headers=headers, timeout=25)
                if response.status_code in (429, 500, 502, 503, 504):
                    wait_time = attempt * 3
                    print(f"[JournalFetcher] ⚠️ OpenAlex {response.status_code}. Retrying in {wait_time}s (attempt {attempt}/{max_retries})...")
                    time.sleep(wait_time)
                    continue
                response.raise_for_status()
                data = response.json()
                break
            except requests.RequestException as e:
                if attempt == max_retries:
                    print(f"[JournalFetcher] Error fetching data from OpenAlex after {max_retries} attempts: {e}")
                    return []
                wait_time = attempt * 3
                print(f"[JournalFetcher] ⚠️ Request error ({e}). Retrying in {wait_time}s...")
                time.sleep(wait_time)

        if not data:
            return []
        results = data.get("results", [])

        papers: List[Paper] = []
        for item in results:
            title = item.get("title") or "Untitled"
            doi = item.get("doi") or ""
            work_id = item.get("id") or ""
            unique_id = f"doi:{doi}" if doi else f"openalex:{work_id.split('/')[-1]}"

            # Publication date
            pub_date_str = item.get("publication_date")
            try:
                pub_date = datetime.fromisoformat(pub_date_str).replace(tzinfo=timezone.utc)
            except Exception:
                pub_date = now

            # Source Venue
            primary_loc = item.get("primary_location") or {}
            source_info = primary_loc.get("source") or {}
            venue_name = source_info.get("display_name") or "Peer-Reviewed Journal"

            # URL & PDF
            url = doi or primary_loc.get("landing_page_url") or f"https://openalex.org/{work_id.split('/')[-1]}"
            pdf_url = item.get("open_access", {}).get("oa_url") or None

            # Authors
            authors = []
            for auth in item.get("authorships", []):
                author_obj = auth.get("author", {})
                author_name = author_obj.get("display_name")
                if author_name:
                    authors.append(author_name)

            abstract = self._reconstruct_abstract(item.get("abstract_inverted_index"))
            if not abstract or len(abstract.strip()) < 80 or "no abstract available" in abstract.lower():
                fallback_abstract = self._fetch_abstract_from_arxiv(title)
                if fallback_abstract:
                    abstract = fallback_abstract
                else:
                    # Skip papers without an abstract to prevent empty/meaningless summaries
                    continue

            # Concepts/Categories
            categories = [c.get("display_name") for c in item.get("concepts", [])[:3] if c.get("display_name")]

            paper = Paper(
                id=unique_id,
                title=title,
                authors=authors,
                abstract=abstract,
                published=pub_date,
                url=url,
                pdf_url=pdf_url,
                categories=categories,
                source="journal",
                venue=venue_name
            )
            papers.append(paper)

        return papers
