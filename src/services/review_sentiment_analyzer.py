"""Review Sentiment Analyzer.

Extracts pain points and improvement signals from product reviews
using LLM analysis.  Identifies keywords that should be reflected
in listing content (bullets, A+, Q&A).

Data sources (by availability):
  1. Customer Feedback API (Brand Analytics role required) — topic summaries
  2. Manual review text input — LLM analysis of provided reviews
  3. Ad Search Term Report — indirect customer language signals
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ReviewInsight:
    """One insight extracted from review analysis."""

    topic: str = ""  # e.g. "Assembly difficulty", "Color accuracy"
    sentiment: str = "negative"  # positive / negative / neutral
    frequency: int = 0
    representative_quote: str = ""
    recommended_action: str = ""
    related_keywords: List[str] = field(default_factory=list)


@dataclass
class ReviewAnalysisResult:
    """Aggregated review analysis for a product."""

    asin: str = ""
    total_reviews_analyzed: int = 0
    insights: List[ReviewInsight] = field(default_factory=list)
    top_pain_points: List[str] = field(default_factory=list)
    listing_improvement_suggestions: List[str] = field(default_factory=list)
    keyword_opportunities: List[str] = field(default_factory=list)
    raw_analysis: str = ""


class ReviewSentimentAnalyzer:
    """LLM-powered review insight extraction."""

    _ANALYSIS_PROMPT = """You are an Amazon product manager analyzing customer reviews.
    Extract actionable insights from the review data below.

    ▼ REVIEW DATA:
    {review_data}

    ▼ ANALYSIS TASKS:
    1. Identify TOP 5 pain points (negative sentiment, high frequency)
    2. Identify TOP 3 things customers LOVE (positive sentiment)
    3. For each pain point, suggest:
       - How to address it in listing content (bullets/A+/Q&A)
       - Keywords/phrases customers use to describe this issue
    4. Extract 10 keywords/phrases that customers use that are NOT in typical listing copy
    5. Recommend 3 listing improvement actions (specific, actionable)

    ▼ OUTPUT (strict JSON):
    {{
      "pain_points": [
        {{
          "topic": "string",
          "frequency_estimate": "high/medium/low",
          "customer_language": "how customers describe it",
          "listing_fix": "specific content change to address this"
        }}
      ],
      "positive_signals": [
        {{
          "topic": "string",
          "customer_language": "how customers praise it"
        }}
      ],
      "customer_keywords": ["keyword1", "keyword2", ...],
      "listing_improvements": ["action 1", "action 2", "action 3"]
    }}

    Return ONLY valid JSON. No other text."""

    def __init__(self, llm_service: Any = None):
        self._llm = llm_service

    def analyze_reviews(
        self,
        asin: str,
        reviews: List[Dict[str, str]],
    ) -> ReviewAnalysisResult:
        """Analyze a batch of review texts.

        Args:
            asin: Product ASIN.
            reviews: List of dicts with keys: rating (1-5), title, body, date.

        Returns:
            ReviewAnalysisResult with extracted insights.
        """
        result = ReviewAnalysisResult(
            asin=asin,
            total_reviews_analyzed=len(reviews),
        )

        if not reviews:
            result.listing_improvement_suggestions.append(
                "No reviews available. Consider Vine program for initial reviews."
            )
            return result

        review_text = self._format_reviews(reviews)
        analysis = self._call_llm_analysis(review_text)
        if analysis is None:
            return result

        result.raw_analysis = json.dumps(analysis)

        # Parse pain points
        for pp in analysis.get("pain_points", []):
            insight = ReviewInsight(
                topic=pp.get("topic", ""),
                sentiment="negative",
                representative_quote=pp.get("customer_language", ""),
                recommended_action=pp.get("listing_fix", ""),
            )
            freq = pp.get("frequency_estimate", "low")
            insight.frequency = {"high": 10, "medium": 5, "low": 2}.get(freq, 2)
            result.insights.append(insight)
            result.top_pain_points.append(f"{insight.topic}: {insight.recommended_action}")

        # Parse positive signals
        for ps in analysis.get("positive_signals", []):
            result.insights.append(ReviewInsight(
                topic=ps.get("topic", ""),
                sentiment="positive",
                representative_quote=ps.get("customer_language", ""),
            ))

        result.keyword_opportunities = analysis.get("customer_keywords", [])
        result.listing_improvement_suggestions = analysis.get("listing_improvements", [])

        logger.info(
            "Review analysis for %s: %d insights, %d keywords",
            asin,
            len(result.insights),
            len(result.keyword_opportunities),
        )
        return result

    def analyze_from_feedback_api(
        self,
        asin: str,
        topics_data: List[Dict[str, Any]],
    ) -> ReviewAnalysisResult:
        """Analyze review topics from Customer Feedback API.

        Args:
            asin: Product ASIN.
            topics_data: Raw response from getItemReviewTopics.
        """
        reviews = []
        for topic in topics_data:
            sentiment = "negative" if topic.get("sentiment", "").lower() == "negative" else "positive"
            text = topic.get("topic", "") + ": " + (topic.get("summary", "") or "")
            reviews.append({
                "rating": 1 if sentiment == "negative" else 5,
                "title": topic.get("topic", ""),
                "body": text,
                "date": "",
            })
        return self.analyze_reviews(asin, reviews)

    def _format_reviews(self, reviews: List[Dict[str, str]]) -> str:
        lines = []
        for i, r in enumerate(reviews[:50]):  # limit for LLM context
            rating = r.get("rating", "?")
            stars = "⭐" * int(rating) if isinstance(rating, (int, float)) else rating
            lines.append(
                f"[{stars}] {r.get('title', '')}\n"
                f"  {r.get('body', '')[:200]}\n"
            )
        return "\n".join(lines)

    def _call_llm_analysis(self, review_text: str) -> Optional[Dict]:
        try:
            llm = self._get_llm()
            from infrastructure.llm.types import LLMRequest

            request = LLMRequest(
                task_type="review_analysis",
                system_prompt="You are a product management analyst. Return ONLY valid JSON.",
                user_prompt=self._ANALYSIS_PROMPT.format(review_data=review_text),
                json_mode=True,
                temperature=0.2,
            )
            response = llm.generate(request)
            raw = response.content if hasattr(response, "content") else str(response)
            if isinstance(raw, dict):
                return raw
            text = str(raw).strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:]) if lines[0].startswith("```") else text
                if text.endswith("```"):
                    text = text[:-3]
            return json.loads(text)
        except Exception as exc:
            logger.error("Review LLM analysis failed: %s", exc)
            return None

    def _get_llm(self):
        if self._llm is not None:
            return self._llm
        from infrastructure.llm.factory import get_llm_service
        self._llm = get_llm_service()
        return self._llm
