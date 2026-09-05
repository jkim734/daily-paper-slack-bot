import json
import re
from typing import List, Optional, Dict, Any
import requests
from pydantic import BaseModel, Field

from .fetchers.base import Paper
from .config import SummarizerConfig


class PaperSummary(BaseModel):
    paper: Paper
    relevance_score: int = Field(default=5, description="1-10 점수")
    one_line_summary: str = Field(default="", description="1줄 핵심 요약 (20~50자)")
    problem: str = Field(default="", description="풀려는 문제 (2~3문장)")
    method: str = Field(default="", description="접근 방법 (2~4문장)")
    result: str = Field(default="", description="핵심 결과 (2~3문장)")
    contribution: str = Field(default="", description="기여점 / 새로운 점 (1~2문장)")
    key_points: List[str] = Field(default_factory=list, description="핵심 포인트 리스트")
    tags: List[str] = Field(default_factory=list, description="주요 키워드 태그")
    notion_url: Optional[str] = Field(default=None, description="노션 페이지 URL")


class Summarizer:
    def __init__(self, config: SummarizerConfig, gemini_api_key: Optional[str] = None, openai_api_key: Optional[str] = None):
        self.config = config
        self.gemini_api_key = gemini_api_key or ""
        self.openai_api_key = openai_api_key or ""

    def summarize_and_rank(self, papers: List[Paper]) -> List[PaperSummary]:
        if not papers:
            return []

        # If no API key provided, fall back to mock summarizer
        max_k = getattr(self.config, "max_k", self.config.top_k)
        if self.config.provider == "gemini" and not self.gemini_api_key:
            print("[Summarizer] Warning: GEMINI_API_KEY is not set. Generating mock/extractive summary.")
            return self._mock_summaries(papers[:max_k])
        elif self.config.provider == "openai" and not self.openai_api_key:
            print("[Summarizer] Warning: OPENAI_API_KEY is not set. Generating mock/extractive summary.")
            return self._mock_summaries(papers[:max_k])

        prompt = self._build_prompt(papers)

        try:
            if self.config.provider == "gemini":
                raw_response = self._call_gemini(prompt)
            else:
                raw_response = self._call_openai(prompt)

            summaries = self._parse_llm_response(raw_response, papers)
            if summaries:
                return summaries
            else:
                print("[Summarizer] Failed to parse structured JSON from LLM. Falling back to mock summary.")
                return self._mock_summaries(papers[:max_k])
        except Exception as e:
            print(f"[Summarizer] LLM error: {e}. Falling back to extractive summary.")
            return self._mock_summaries(papers[:max_k])

    def _build_prompt(self, papers: List[Paper]) -> str:
        interest_prompt = f"사용자의 연구 관심 분야: {self.config.research_interest}\n" if self.config.research_interest else ""
        min_k = getattr(self.config, "min_k", 5)
        max_k = getattr(self.config, "max_k", 10)
        
        papers_text = []
        for i, p in enumerate(papers, 1):
            venue_info = f"게재/출처: {p.venue}\n" if p.venue else ""
            papers_text.append(
                f"[논문 {i}]\n"
                f"ID: {p.id}\n"
                f"제목: {p.clean_title()}\n"
                f"{venue_info}"
                f"초록: {p.clean_abstract()}\n"
            )
        papers_str = "\n".join(papers_text)

        lang_instruction = "모든 요약과 설명은 명확하고 전문적인 한국어로 작성하세요. 논문 초록에 근거해 객관적으로 작성하고 추측하지 마세요." if self.config.language == "ko" else "Write all summaries in English based strictly on the abstract."

        return f"""당신은 세계 최고 수준의 양자컴퓨팅 및 컴퓨터공학 전문 연구원입니다.
아래 제공된 최근 논문 목록 중에서 {interest_prompt}에 가장 적합하고 수준 높은 논문을 최소 {min_k}편에서 최대 {max_k}편 선별하여 핵심을 명확하게 요약해 주세요. (가용한 후보 논문이 충분하다면 최대 {max_k}편을 선별하고, 적어도 {min_k}편 이상을 포함해 주세요.)

{lang_instruction}

선별할 각 논문에 대해 아래 JSON 배열 형식으로만 응답하세요. 마크다운 코드블록(```json ... ```)을 포함해도 좋습니다:

[
  {{
    "paper_id": "논문 ID (예: arxiv:... 또는 doi:...)",
    "relevance_score": 1부터 10 사이의 정수 (연구 관심사와의 관련성),
    "one_line_summary": "이 논문이 무엇을 하는 논문인지 한눈에 알 수 있는 한 문장 요약 (20~50자)",
    "problem": "기존 연구의 한계 및 이 논문에서 다루는 핵심 문제 또는 공백 (2~3문장)",
    "method": "어떻게 해결했는지 - 제안하는 모델, 양자 알고리즘, 오류정정 코드, 회로 설계, 실험 방법 등 (2~4문장)",
    "result": "무엇을 발견/달성했는지, 실험 결과 및 수치가 있다면 포함 (2~3문장)",
    "contribution": "기존 대비 무엇이 다르고 중요한지 - 주요 기여점 및 혁신성 (1~2문장)",
    "tags": ["#태그1", "#태그2", "#태그3"]
  }}
]

논문 목록:
{papers_str}
"""

    def _call_gemini(self, prompt: str) -> str:
        from google import genai
        client = genai.Client(api_key=self.gemini_api_key)
        # Using configured model, e.g., gemini-2.5-flash
        model_name = self.config.model if self.config.model else "gemini-2.5-flash"
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
        )
        return response.text or ""

    def _call_openai(self, prompt: str) -> str:
        headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json"
        }
        model_name = self.config.model if self.config.model else "gpt-4o-mini"
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": "You are an expert AI research assistant. Output strictly valid JSON."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2
        }
        res = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=60)
        res.raise_for_status()
        data = res.json()
        return data["choices"][0]["message"]["content"]

    def _parse_llm_response(self, raw_text: str, papers: List[Paper]) -> List[PaperSummary]:
        paper_map = {p.id: p for p in papers}

        # Extract JSON content from markdown block if present
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_text)
        if json_match:
            clean_json = json_match.group(1)
        else:
            clean_json = raw_text.strip()

        try:
            items = json.loads(clean_json)
        except Exception:
            # Try to locate array bracket
            bracket_match = re.search(r"\[\s*\{[\s\S]*\}\s*\]", clean_json)
            if bracket_match:
                items = json.loads(bracket_match.group(0))
            else:
                return []

        summaries: List[PaperSummary] = []
        for item in items:
            p_id = item.get("paper_id")
            if p_id in paper_map:
                p = paper_map[p_id]
                problem = item.get("problem", "")
                method = item.get("method", "")
                result = item.get("result", "")
                contrib = item.get("contribution", "")
                key_points = item.get("key_points") or []
                if not key_points and (problem or method or result or contrib):
                    if problem: key_points.append(f"풀려는 문제: {problem}")
                    if method: key_points.append(f"접근 방법: {method}")
                    if result: key_points.append(f"핵심 결과: {result}")
                    if contrib: key_points.append(f"기여점: {contrib}")

                summary = PaperSummary(
                    paper=p,
                    relevance_score=int(item.get("relevance_score", 7)),
                    one_line_summary=item.get("one_line_summary", ""),
                    problem=problem,
                    method=method,
                    result=result,
                    contribution=contrib,
                    key_points=key_points,
                    tags=item.get("tags", [])
                )
                summaries.append(summary)

        # Sort by relevance score descending
        max_k = getattr(self.config, "max_k", self.config.top_k)
        summaries.sort(key=lambda s: s.relevance_score, reverse=True)
        return summaries[:max_k]

    def _mock_summaries(self, papers: List[Paper]) -> List[PaperSummary]:
        """Provides extractive fallback summary when LLM API keys are not provided."""
        results = []
        for p in papers:
            sentences = [s.strip() for s in re.split(r'(?<=[.?!])\s+', p.clean_abstract()) if s.strip()]
            one_line = sentences[0] if sentences else p.clean_title()
            problem = sentences[0] if len(sentences) > 0 else ""
            method = sentences[1] if len(sentences) > 1 else ""
            result = sentences[2] if len(sentences) > 2 else ""
            contrib = sentences[-1] if len(sentences) > 3 else ""

            key_points = [
                f"풀려는 문제: {problem[:150]}...",
                f"접근 방법: {method[:150]}...",
                f"핵심 결과: {result[:150]}..."
            ]
            if contrib:
                key_points.append(f"기여점: {contrib[:150]}...")

            tags = [f"#{cat}" for cat in p.categories[:3]] or ["#양자컴퓨팅", "#연구"]
            results.append(PaperSummary(
                paper=p,
                relevance_score=8,
                one_line_summary=f"[요약] {one_line}",
                problem=problem,
                method=method,
                result=result,
                contribution=contrib,
                key_points=key_points,
                tags=tags
            ))
        return results
