import re
import requests
from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field

from .base import Paper, BaseFetcher


class ScirateConfig(BaseModel):
    categories: List[str] = Field(default_factory=lambda: ["quant-ph"])
    range_days: int = 3
    min_scites: int = 3
    max_results: int = 30


class ScirateFetcher(BaseFetcher):
    BASE_URL = "https://scirate.com/arxiv"
    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Linux"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1"
    }

    def __init__(self, config: ScirateConfig):
        self.config = config

    def fetch_recent_papers(self, lookback_days: Optional[int] = None) -> List[Paper]:
        """Fetches trending papers from SciRate categorized feeds, ordered by community Scites (upvotes)."""
        papers: List[Paper] = []
        seen_ids = set()

        # Map lookback_days to valid SciRate range parameter (1, 3, 7, 31)
        target_range = lookback_days or self.config.range_days
        if target_range <= 1:
            range_param = 1
        elif target_range <= 4:
            range_param = 3
        elif target_range <= 14:
            range_param = 7
        else:
            range_param = 31

        for category in self.config.categories:
            url = f"{self.BASE_URL}/{category}?range={range_param}"
            html = ""
            try:
                res = requests.get(url, headers=self.DEFAULT_HEADERS, timeout=20)
                if res.status_code == 200:
                    html = res.text
                elif res.status_code == 403:
                    # Fallback to curl subprocess if Cloudflare challenges python TLS fingerprint
                    import subprocess
                    curl_cmd = [
                        "curl", "-sL",
                        "-A", self.DEFAULT_HEADERS["User-Agent"],
                        "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "-H", "Accept-Language: en-US,en;q=0.9",
                        url
                    ]
                    proc = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=20)
                    if proc.returncode == 0 and '<li class="paper' in proc.stdout:
                        html = proc.stdout
                    else:
                        print(f"[ScirateFetcher] ⚠️ HTTP {res.status_code} fetching category '{category}' from {url}")
                        continue
                else:
                    print(f"[ScirateFetcher] ⚠️ HTTP {res.status_code} fetching category '{category}' from {url}")
                    continue

                cat_papers = self._parse_html(html, default_category=category)
                for p in cat_papers:
                    if p.id not in seen_ids and (p.scites or 0) >= self.config.min_scites:
                        seen_ids.add(p.id)
                        papers.append(p)

            except Exception as e:
                print(f"[ScirateFetcher] ❌ Error fetching SciRate ({category}): {e}")

        # Sort by Scites count descending
        papers.sort(key=lambda p: (p.scites or 0), reverse=True)
        return papers[:self.config.max_results]

    def _parse_html(self, html: str, default_category: str = "quant-ph") -> List[Paper]:
        results: List[Paper] = []
        blocks = re.findall(r'<li class="paper tex2jax">([\s\S]*?)</li>', html)

        for b in blocks:
            # 1. Title and arXiv ID
            title_m = re.search(r'<div class="title"><a href="/arxiv/([^"]+)">([^<]+)</a>', b)
            if not title_m:
                continue
            arxiv_id = title_m.group(1).strip()
            # Clean possible version suffix from id (e.g. 2609.03065v1 -> 2609.03065)
            clean_id = re.sub(r'v\d+$', '', arxiv_id)
            title = " ".join(title_m.group(2).replace("\n", " ").split())

            # 2. Scites count
            count_m = re.search(r'<button class="btn btn-default count">(\d+)</button>', b)
            scites = int(count_m.group(1)) if count_m else 0

            # 3. Abstract
            abstract_m = re.search(r'<div class="abstract[^"]*">([\s\S]*?)</div>', b)
            abstract = " ".join(abstract_m.group(1).replace("\n", " ").split()) if abstract_m else ""

            # 4. Authors
            author_matches = re.findall(r'<a href="/search\?q=au:[^"]+">([^<]+)</a>', b)
            authors = [" ".join(a.rstrip(",").replace("\n", " ").split()) for a in author_matches]

            # 5. Publication Date
            uid_m = re.search(r'<div class="uid">([^<]+)', b)
            pub_date = datetime.now(timezone.utc)
            if uid_m:
                date_str = uid_m.group(1).strip()
                try:
                    pub_date = datetime.strptime(date_str, "%b %d %Y").replace(tzinfo=timezone.utc)
                except Exception:
                    pass

            # 6. Categories
            cat_matches = re.findall(r'<a href="/arxiv/([a-zA-Z0-9\.\-]+)">', b)
            categories = list(dict.fromkeys(cat_matches)) if cat_matches else [default_category]

            paper = Paper(
                id=f"arxiv:{clean_id}",
                title=title,
                authors=authors,
                abstract=abstract,
                published=pub_date,
                url=f"https://arxiv.org/abs/{clean_id}",
                pdf_url=f"https://arxiv.org/pdf/{clean_id}.pdf",
                categories=categories,
                source="scirate",
                venue=f"arXiv (🔥 SciRate {scites} Scites)" if scites > 0 else "arXiv",
                scites=scites,
                scirate_url=f"https://scirate.com/arxiv/{clean_id}"
            )
            results.append(paper)

        return results
