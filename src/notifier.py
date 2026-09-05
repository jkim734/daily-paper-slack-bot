from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import requests

from .summarizer import PaperSummary
from .config import SlackConfig


class SlackNotifier:
    def __init__(self, webhook_url: Optional[str], config: SlackConfig):
        self.webhook_url = webhook_url or ""
        self.config = config

    def send_test_message(self) -> bool:
        """Sends a verification message to ensure Slack webhook is configured properly."""
        if not self.webhook_url:
            print("[SlackNotifier] Error: SLACK_WEBHOOK_URL is not set.")
            return False

        payload = {
            "username": self.config.bot_name,
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "🎉 Daily Paper Bot 연동 테스트 성공!",
                        "emoji": True
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "슬랙 웹훅이 정상적으로 연결되었습니다.\n내일부터 지정된 시각에 최신 연구 논문 요약 브리핑이 이곳으로 전송됩니다."
                    }
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"📅 테스트 전송 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        }
                    ]
                }
            ]
        }
        self._apply_icon(payload)

        return self._post_payload(payload)

    def format_blocks(self, summaries: List[PaperSummary], date_str: Optional[str] = None) -> List[Dict[str, Any]]:
        """Constructs a Slack Block Kit payload from paper summaries."""
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")

        blocks: List[Dict[str, Any]] = []

        # 1. Header Block
        blocks.append({
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"📚 {self.config.header_title} ({date_str})",
                "emoji": True
            }
        })

        # 2. Context Intro
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"총 *{len(summaries)}편*의 엄선된 최신 논문 브리핑입니다."
                }
            ]
        })
        blocks.append({"type": "divider"})

        # 3. Paper Sections
        for i, item in enumerate(summaries, 1):
            p = item.paper
            authors_str = ", ".join(p.authors[:3])
            if len(p.authors) > 3:
                authors_str += f" 외 {len(p.authors) - 3}명"

            pub_date_str = p.published.strftime("%Y-%m-%d")

            # Title & Main Link
            title_md = f"*{i}. <{p.url}|{p.clean_title()}>*"
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": title_md
                }
            })

            # Metadata info
            meta_parts = []
            if p.venue and "scirate" not in p.venue.lower():
                meta_parts.append(f"🏛️ *게재*: *{p.venue}*")
            elif p.source in ("arxiv", "scirate"):
                meta_parts.append("📄 *출처*: arXiv")

            if p.scites is not None and p.scites > 0:
                scirate_url = p.scirate_url or f"https://scirate.com/arxiv/{p.id.replace('arxiv:', '')}"
                meta_parts.append(f"🔥 <{scirate_url}|*SciRate {p.scites} Scites*>")

            meta_parts.append(f"👤 *저자*: {authors_str or 'N/A'}")
            meta_parts.append(f"📅 *일자*: {pub_date_str}")
            if p.pdf_url:
                meta_parts.append(f"🔗 <{p.pdf_url}|PDF 원문>")

            blocks.append({
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": " | ".join(meta_parts)
                    }
                ]
            })

            # One line summary
            if item.one_line_summary:
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"💡 *한 줄 요약*: *{item.one_line_summary}*"
                    }
                })

            # Details (간결하고 직관적인 개조식)
            detail_lines = []
            if item.problem:
                detail_lines.append(f"• *풀려는 문제*: {item.problem}")
            if item.method:
                detail_lines.append(f"• *접근 방법*: {item.method}")
            if item.result:
                detail_lines.append(f"• *핵심 성과*: {item.result}")
            if item.contribution:
                detail_lines.append(f"• *의의/기여*: {item.contribution}")

            if not detail_lines and item.key_points:
                detail_lines = [f"• {pt}" for pt in item.key_points]

            if detail_lines:
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "\n".join(detail_lines)
                    }
                })

            # Key terms (핵심 용어 쏙쏙)
            if item.key_terms:
                term_texts = []
                for kt in item.key_terms:
                    if isinstance(kt, dict):
                        t_name = kt.get("term", "").strip()
                        t_def = kt.get("definition", "").strip()
                        if t_name and t_def:
                            term_texts.append(f"▫️ *{t_name}*: {t_def}")
                    elif isinstance(kt, str) and kt.strip():
                        term_texts.append(f"▫️ {kt.strip()}")
                if term_texts:
                    blocks.append({
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*📖 핵심 용어 쏙쏙:*\n" + "\n".join(term_texts)
                        }
                    })

            # Tags & Notion Link
            footer_elements = []
            if item.tags:
                tag_str = " ".join(f"`{t}`" for t in item.tags)
                footer_elements.append({
                    "type": "mrkdwn",
                    "text": f"🏷️ {tag_str}"
                })
            if p.scirate_url:
                footer_elements.append({
                    "type": "mrkdwn",
                    "text": f"💬 <{p.scirate_url}|SciRate 토론>"
                })
            if item.notion_url:
                footer_elements.append({
                    "type": "mrkdwn",
                    "text": f"📝 <{item.notion_url}|Notion에서 보기>"
                })

            if footer_elements:
                blocks.append({
                    "type": "context",
                    "elements": footer_elements
                })

            blocks.append({"type": "divider"})

        # 4. Footer
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "🤖 _Daily Research Paper Notifier · Google Gemini Powered_"
                }
            ]
        })

        return blocks

    def send_summaries(self, summaries: List[PaperSummary], dry_run: bool = False) -> bool:
        if not summaries:
            print("[SlackNotifier] No summaries to send.")
            return True

        blocks = self.format_blocks(summaries)

        if dry_run or not self.webhook_url:
            print("\n" + "=" * 60)
            print("[SlackNotifier] DRY RUN / PREVIEW MODE (Not sent to Slack)")
            print("=" * 60)
            for i, s in enumerate(summaries, 1):
                p = s.paper
                print(f"\n[{i}] {p.clean_title()}")
                print(f"    - URL: {p.url}")
                print(f"    - Authors: {', '.join(p.authors[:2])}")
                print(f"    - Summary: {s.one_line_summary}")
                for kp in s.key_points:
                    print(f"      * {kp}")
                if s.key_terms:
                    print("      * 📖 핵심 용어 해설:")
                    for kt in s.key_terms:
                        if isinstance(kt, dict):
                            print(f"        - {kt.get('term')}: {kt.get('definition')}")
                        else:
                            print(f"        - {kt}")
                print(f"    - Tags: {' '.join(s.tags)}")
            print("=" * 60 + "\n")
            return True

        # Slack has a limit of 50 blocks per message
        chunk_size = 45
        success = True
        for i in range(0, len(blocks), chunk_size):
            chunk = blocks[i:i + chunk_size]
            payload = {
                "username": self.config.bot_name,
                "blocks": chunk
            }
            self._apply_icon(payload)
            if not self._post_payload(payload):
                success = False

        return success

    def _apply_icon(self, payload: Dict[str, Any]):
        """Sets icon_url if configured, otherwise falls back to icon_emoji."""
        if getattr(self.config, "bot_icon_url", None):
            payload["icon_url"] = self.config.bot_icon_url
        elif getattr(self.config, "bot_icon_emoji", None):
            payload["icon_emoji"] = self.config.bot_icon_emoji

    def _post_payload(self, payload: Dict[str, Any]) -> bool:
        try:
            res = requests.post(self.webhook_url, json=payload, timeout=15)
            if res.status_code == 200:
                print("[SlackNotifier] Message posted successfully.")
                return True
            else:
                print(f"[SlackNotifier] Failed to post message. Status: {res.status_code}, Body: {res.text}")
                return False
        except requests.RequestException as e:
            print(f"[SlackNotifier] Request error while posting to Slack: {e}")
            return False
