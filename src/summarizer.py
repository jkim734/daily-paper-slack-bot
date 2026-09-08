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
    one_line_summary: str = Field(default="", description="1줄 핵심 요약 (20~40자)")
    problem: str = Field(default="", description="풀려는 문제 (1~2문장)")
    method: str = Field(default="", description="접근 방법 (1~2문장)")
    result: str = Field(default="", description="핵심 결과 (1~2문장)")
    contribution: str = Field(default="", description="기여점 / 의의 (1문장)")
    key_terms: List[Dict[str, str]] = Field(default_factory=list, description="핵심 용어 및 쉬운 뜻 해설")
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
            scite_info = f"커뮤니티 추천(SciRate): {p.scites} Scites (연구자들의 높은 관심 및 추천)\n" if p.scites else ""
            papers_text.append(
                f"[논문 {i}]\n"
                f"ID: {p.id}\n"
                f"제목: {p.clean_title()}\n"
                f"{venue_info}"
                f"{scite_info}"
                f"초록: {p.clean_abstract()}\n"
            )
        papers_str = "\n".join(papers_text)

        lang_instruction = """【언어 및 작성 원칙 - 필수 준수】
1. 논문 제목(Title)은 원문 그대로 유지하되, 제목을 제외한 모든 요약, 해설, 용어 설명은 100% 자연스럽고 명쾌한 한국어로 작성하세요.
2. 【가독성 및 간결성 극대화】:
   - 길고 복잡한 만연체 문장을 철저히 배제하고, 읽는 즉시 핵심이 직관적으로 이해되도록 간결하고 명확한 문체로 작성하세요.
    - 한 줄 요약: 논문의 핵심을 20~40자로 명쾌하게 압축 (군더더기 없이 본질 제시)
    - 문제: 기존 기술의 한계 및 병목을 1~2문장으로 간결 제시
    - 접근: 제안하는 핵심 아이디어와 해결 방식을 1~2문장으로 명확히 요약
    - 성과: 가장 중요한 성과와 핵심 수치 위주로 1~2문장 정리
    - 의의/기여: 이 연구가 분야에 미치는 실질적 의의를 1문장으로 임팩트 있게 정리
3. 【핵심 용어 (key_terms) 필수 - 용어명은 영문 표기】:
   - 이 논문을 깊이 있게 이해하기 위해 필요한 구체적이고 전문적인 핵심 개념/기법 2~3개를 선별하세요.
   - ⚠️ 【절대 금지 - 기본 용어 제외】:
     "Quantum Computing", "Quantum Computer", "Qubit", "Quantum Algorithm", "Superposition", "Entanglement" 등 양자 분야 연구자나 독자라면 누구나 이미 알고 있는 너무 기초적이고 일반적인 개념은 절대로 용어 사전에 포함하지 마세요!
   - 🎯 【포함할 대상】:
     오직 해당 논문의 핵심 주제와 직접 관련된 특화된 기술, 모델, 부호, 알고리즘(예: "Surface Code", "Floquet Code", "Magic State Distillation", "Transmon", "Caldeira-Leggett Model", "TLS-defect", "Chain Map Hierarchy", "qLDPC Code", "Grover Search" 등)만 선별하세요.
   - 용어명(term)은 원래의 영문(English) 그대로 간결하게 작성하세요.
   - 뜻 설명(definition)은 초심자나 인접 분야 연구자도 즉시 직관적으로 이해할 수 있도록 쉽고 친절한 한국어로 1문장씩 풀어주세요.
   - 예: term: "Surface Code", definition: "큐비트를 2차원 바둑판처럼 배열해 연산 중 생기는 오류를 실시간으로 찾아내고 고치는 대표적인 양자 오류정정 기술"
   - 예: term: "Magic State Distillation", definition: "노이즈가 낀 보조 큐비트들을 정제하여 복잡한 고난도 양자 계산을 가능하게 해주는 고순도 상태를 만드는 과정"
4. 태그(tags)는 '#양자오류정정', '#표면코드', '#QAOA' 등 핵심 한글 태그 3~5개로 작성하세요.""" if self.config.language == "ko" else "Write all summaries in English based strictly on the abstract."

        return f"""당신은 세계 최고 수준의 양자컴퓨팅 및 양자정보 전문 연구원입니다.
아래 제공된 최근 논문 목록 중에서 {interest_prompt}에 가장 적합하고 가치 있는 논문을 엄선하여 최소 {min_k}편에서 최대 {max_k}편 선별하고, 핵심을 명확하게 요약해 주세요. (가용한 후보 논문이 충분하다면 최대 {max_k}편을 선별하고, 적어도 {min_k}편 이상을 포함해 주세요.)

【논문 엄선 기준 (1~10점 평가 지표)】
1. 연구 주제 일치도 (40%): 양자오류정정(QEC), 표면코드, 결함허용 양자연산, 양자알고리즘(VQE, QAOA 등), QML과의 직접적인 연관성
2. 기술적 독창성 및 기여도 (30%): 기존 기법 대비 새로운 돌파구(Breakthrough), 오류 임계치 개선, 회로 깊이 단축, 알고리즘 효율성 제고 등
3. 학술적 권위 및 커뮤니티 추천도 (20%): 최고 권위 피어리뷰 저널(Nature, PRL, Quantum 등) 게재 논문 및 SciRate에서 많은 추천(Scites)을 받은 커뮤니티 검증 논문 우선
4. 구체성 및 완성도 (10%): 단순 추상이 아닌 구체적인 수치, 실험 결과, 시뮬레이션 데이터의 명확성

{lang_instruction}

선별할 각 논문에 대해 아래 JSON 배열 형식으로만 응답하세요. 마크다운 코드블록(```json ... ```)을 포함해도 좋습니다:

[
  {{
    "paper_id": "논문 ID (예: arxiv:... 또는 doi:...)",
    "relevance_score": 1부터 10 사이의 정수 (위 엄선 기준에 따른 점수),
    "one_line_summary": "핵심을 명쾌하게 압축한 직관적 1문장 (20~40자)",
    "problem": "기존 연구의 한계/병목 (1~2문장으로 간결하게)",
    "method": "제안하는 핵심 아이디어/해결법 (1~2문장으로 명확하게)",
    "result": "핵심 성과 및 주요 수치 (1~2문장으로 압축)",
    "contribution": "이 논문의 핵심 의의 및 가치 (1문장)",
    "key_terms": [
      {{
        "term": "Surface Code",
        "definition": "초심자도 바로 이해할 수 있는 쉽고 직관적인 1문장 뜻 풀이 (한국어)"
      }},
      {{
        "term": "Magic State Distillation",
        "definition": "초심자도 바로 이해할 수 있는 쉽고 직관적인 1문장 뜻 풀이 (한국어)"
      }}
    ],
    "tags": ["#양자오류정정", "#표면코드", "#결함허용"]
  }}
]

논문 목록:
{papers_str}
"""

    def _call_gemini(self, prompt: str) -> str:
        import time
        from google import genai
        client = genai.Client(api_key=self.gemini_api_key)

        # Strict hierarchy: 3.8-flash -> 3.7-flash -> 3.6-flash -> 3.5-flash -> flash-latest
        hierarchy = [
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-flash-latest"
        ]

        # Respect user configured model if custom, else maintain hierarchy
        if self.config.model and self.config.model not in hierarchy:
            hierarchy.insert(0, self.config.model)

        last_error = None
        for i, model_name in enumerate(hierarchy):
            next_model = hierarchy[i + 1] if i + 1 < len(hierarchy) else "None"
            print(f"[Summarizer] 🚀 Attempting summary with model: '{model_name}'...")

            for attempt in range(1, 3):
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                    )
                    if response and response.text:
                        print(f"[Summarizer] ✅ Successfully generated summary using '{model_name}'.")
                        return response.text
                except Exception as e:
                    last_error = e
                    err_str = str(e)
                    # If 429 Quota Exceeded (RPD reached), immediately switch to next model without wasting retries
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "Quota exceeded" in err_str:
                        print(f"[Summarizer] ⚠️ '{model_name}' 할당량 소진 (429 Quota Exceeded). 차상위 모델 '{next_model}'(으)로 즉시 전환합니다.")
                        break
                    elif "503" in err_str or "UNAVAILABLE" in err_str:
                        print(f"[Summarizer] ⚠️ '{model_name}' 일시적 서버 지연(503) (attempt {attempt}/2).")
                        if attempt < 2:
                            time.sleep(2)
                            continue
                        else:
                            print(f"[Summarizer] ⚠️ '{model_name}' 재시도 후에도 불가. 차상위 모델 '{next_model}'(으)로 전환합니다.")
                            break
                    else:
                        print(f"[Summarizer] ⚠️ '{model_name}' 에러 ({err_str[:100]}). 차상위 모델 '{next_model}'(으)로 전환합니다.")
                        break

        raise RuntimeError(f"All Gemini models in hierarchy ({', '.join(hierarchy)}) failed. Last error: {last_error}")

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

        def safe_loads(text: str):
            try:
                return json.loads(text, strict=False)
            except Exception:
                # Sanitize unescaped LaTeX backslashes (\alpha, \mathcal, \approx, \rho, etc.)
                sanitized = re.sub(r"\\(?![\"\\/bfnrt]|u[0-9a-fA-F]{4})", r"\\\\", text)
                return json.loads(sanitized, strict=False)

        try:
            items = safe_loads(clean_json)
        except Exception as e:
            # Try to locate array bracket
            bracket_match = re.search(r"\[\s*\{[\s\S]*\}\s*\]", clean_json)
            if bracket_match:
                try:
                    items = safe_loads(bracket_match.group(0))
                except Exception as inner_e:
                    print(f"[Summarizer] Failed to parse JSON array: {inner_e}")
                    return []
            else:
                print(f"[Summarizer] No JSON array found in response: {e}")
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
                
                # Parse key_terms
                raw_terms = item.get("key_terms", [])
                formatted_terms = []
                if isinstance(raw_terms, list):
                    for kt in raw_terms:
                        if isinstance(kt, dict) and kt.get("term"):
                            formatted_terms.append({
                                "term": str(kt.get("term", "")).strip(),
                                "definition": str(kt.get("definition", "")).strip()
                            })
                        elif isinstance(kt, str) and ":" in kt:
                            parts = kt.split(":", 1)
                            formatted_terms.append({
                                "term": parts[0].strip(),
                                "definition": parts[1].strip()
                            })

                key_points = item.get("key_points") or []
                if not key_points and (problem or method or result or contrib):
                    if problem: key_points.append(f"풀려는 문제: {problem}")
                    if method: key_points.append(f"접근 방법: {method}")
                    if result: key_points.append(f"핵심 결과: {result}")
                    if contrib: key_points.append(f"의의/기여: {contrib}")

                summary = PaperSummary(
                    paper=p,
                    relevance_score=int(item.get("relevance_score", 7)),
                    one_line_summary=item.get("one_line_summary", ""),
                    problem=problem,
                    method=method,
                    result=result,
                    contribution=contrib,
                    key_terms=formatted_terms,
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
            abstract = p.clean_abstract()
            if not abstract or len(abstract.strip()) < 80 or "no abstract available" in abstract.lower():
                continue

            sentences = [s.strip() for s in re.split(r'(?<=[.?!])\s+', abstract) if s.strip()]
            one_line = sentences[0] if sentences else p.clean_title()
            problem = sentences[0] if len(sentences) > 0 else ""
            method = sentences[1] if len(sentences) > 1 else ""
            result = sentences[2] if len(sentences) > 2 else ""
            contrib = sentences[-1] if len(sentences) > 3 else ""

            key_points = [
                f"풀려는 문제: {problem[:150]}...",
                f"접근 방법: {method[:150]}...",
                f"핵심 성과: {result[:150]}..."
            ]
            if contrib:
                key_points.append(f"의의/기여: {contrib[:150]}...")

            # Extract paper-specific technical words from title, never generic 'Quantum Computing'
            title_words = [
                w for w in re.findall(r'[A-Z][a-zA-Z0-9\-]+', p.clean_title())
                if w.lower() not in ["quantum", "computing", "computer", "algorithm", "qubit", "the", "a", "an", "for", "with", "in", "via"]
            ]
            term_name = " ".join(title_words[:2]) if title_words else (p.categories[0] if p.categories else "Key Concept")
            mock_terms = [
                {"term": term_name, "definition": f"해당 연구({p.clean_title()[:35]}...)의 핵심 대상 및 구현 기법"}
            ]

            tags = [f"#{cat}" for cat in p.categories[:3]] or ["#양자연구", "#핵심논문"]
            results.append(PaperSummary(
                paper=p,
                relevance_score=8,
                one_line_summary=f"[요약] {one_line}",
                problem=problem,
                method=method,
                result=result,
                contribution=contrib,
                key_terms=mock_terms,
                key_points=key_points,
                tags=tags
            ))
        return results
