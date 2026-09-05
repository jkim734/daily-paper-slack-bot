from datetime import datetime, timezone, timedelta
from typing import List, Optional
import xml.etree.ElementTree as ET
import requests

from .base import Paper, BaseFetcher
from ..config import PubmedConfig


class PubmedFetcher(BaseFetcher):
    ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

    def __init__(self, config: PubmedConfig):
        self.config = config

    def fetch_recent_papers(self, lookback_days: Optional[int] = None) -> List[Paper]:
        if not self.config.query:
            return []

        days = lookback_days if lookback_days is not None else self.config.lookback_days
        params = {
            "db": "pubmed",
            "term": self.config.query,
            "retmode": "json",
            "retmax": self.config.max_results,
            "sort": "pub_date",
            "reldate": days,
            "datetype": "edat"
        }

        headers = {
            "User-Agent": "DailyPaperSlackBot/1.0 (academic research paper monitor; mailto:contact@example.com)"
        }

        try:
            res = requests.get(self.ESEARCH_URL, params=params, headers=headers, timeout=20)
            res.raise_for_status()
            data = res.json()
            id_list = data.get("esearchresult", {}).get("idlist", [])
        except Exception as e:
            print(f"[PubmedFetcher] Error in esearch: {e}")
            return []

        if not id_list:
            return []

        # Fetch details using efetch (xml)
        fetch_params = {
            "db": "pubmed",
            "id": ",".join(id_list),
            "retmode": "xml"
        }

        try:
            fetch_res = requests.get(self.EFETCH_URL, params=fetch_params, headers=headers, timeout=30)
            fetch_res.raise_for_status()
            return self._parse_pubmed_xml(fetch_res.text)
        except Exception as e:
            print(f"[PubmedFetcher] Error in efetch: {e}")
            return []

    def _parse_pubmed_xml(self, xml_text: str) -> List[Paper]:
        papers: List[Paper] = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            print(f"[PubmedFetcher] XML Parse error: {e}")
            return []

        for article in root.findall(".//PubmedArticle"):
            pmid_elem = article.find(".//MedlineCitation/PMID")
            if pmid_elem is None or not pmid_elem.text:
                continue
            pmid = pmid_elem.text.strip()

            title_elem = article.find(".//ArticleTitle")
            title = "".join(title_elem.itertext()).strip() if title_elem is not None else "Untitled"

            abstract_texts = []
            for ab in article.findall(".//AbstractText"):
                t = "".join(ab.itertext()).strip()
                if t:
                    label = ab.attrib.get("Label")
                    if label:
                        abstract_texts.append(f"{label}: {t}")
                    else:
                        abstract_texts.append(t)
            abstract = " ".join(abstract_texts) if abstract_texts else "No abstract available."

            # Authors
            authors = []
            for author in article.findall(".//AuthorList/Author"):
                last_name = author.find("LastName")
                fore_name = author.find("ForeName")
                if last_name is not None and last_name.text:
                    if fore_name is not None and fore_name.text:
                        authors.append(f"{fore_name.text} {last_name.text}")
                    else:
                        authors.append(last_name.text)

            pub_date = datetime.now(timezone.utc)
            pub_date_elem = article.find(".//JournalIssue/PubDate")
            if pub_date_elem is not None:
                year = pub_date_elem.find("Year")
                if year is not None and year.text:
                    try:
                        pub_date = datetime(int(year.text), 1, 1, tzinfo=timezone.utc)
                    except Exception:
                        pass

            papers.append(Paper(
                id=f"pubmed:{pmid}",
                title=title,
                authors=authors,
                abstract=abstract,
                published=pub_date,
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                source="pubmed"
            ))

        return papers
