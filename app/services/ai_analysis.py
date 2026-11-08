import json
import re
import asyncio
from typing import Dict, Any, Optional, List
from app.core.config import settings
from app.services.llm_provider import llm_service, RateLimitExceeded, LLMProviderError
import logging

logger = logging.getLogger(__name__)

MAX_RESUME_LENGTH = 50000


class ResumeAnalysisService:
    """Service for analyzing resumes using AI via the LLM provider abstraction.

    Requests are routed through Groq -> Gemini -> OpenRouter with automatic
    fallback and per-user rate limiting.
    """

    def __init__(self):
        pass

    async def analyze_resume(
        self, resume_content: str, user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Analyze a resume and provide suggestions using AI.
        """
        if not llm_service.providers:
            raise ValueError("No AI provider configured. Please set GROQ_API_KEY, GEMINI_API_KEY, or OPENROUTER_API_KEY")

        if len(resume_content) > MAX_RESUME_LENGTH:
            raise ValueError(f"Resume content exceeds maximum length of {MAX_RESUME_LENGTH} characters")

        if len(resume_content.strip()) < 50:
            logger.warning(f"Resume content very short ({len(resume_content.strip())} chars), using fallback scoring")
            return self._rule_based_scoring(resume_content)

        prompt = self._build_analysis_prompt(resume_content)
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": "You are a professional resume analyst. Provide detailed analysis in JSON format. The overall_score MUST be an integer between 0 and 100."},
            {"role": "user", "content": prompt},
        ]

        try:
            logger.info("Starting AI resume analysis via LLM provider fallback chain")
            response_text = await llm_service.complete_with_fallback(
                user_id=user_id or 0,
                messages=messages,
                temperature=0.3,
                max_tokens=4000,
            )
            logger.info("AI resume analysis completed successfully")
            return self._parse_ai_response(response_text)
        except RateLimitExceeded as e:
            logger.warning("Rate limit exceeded for user %s: %s", user_id, e)
            raise ValueError(f"AI analysis rate limit exceeded: {str(e)}")
        except LLMProviderError as e:
            logger.error("All LLM providers failed: %s", e)
            raise ValueError(f"AI analysis failed: {str(e)}")
        except Exception as e:
            logger.error("AI analysis failed: %s", e)
            raise ValueError(f"AI analysis failed: {str(e)}")

    async def get_suggestions(
        self, resume_content: str, focus_area: str = "general", user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Get AI suggestions for improving a specific area of the resume."""
        if not llm_service.providers:
            raise ValueError("No AI provider configured")

        prompt = self._build_suggestions_prompt(resume_content, focus_area)
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": "You are a professional resume coach. Provide detailed suggestions in JSON format."},
            {"role": "user", "content": prompt},
        ]

        try:
            logger.info("Generating AI suggestions via LLM provider for focus_area=%s", focus_area)
            response_text = await llm_service.complete_with_fallback(
                user_id=user_id or 0,
                messages=messages,
                temperature=0.3,
                max_tokens=4000,
            )
            logger.info("AI suggestions generated successfully")
            return self._parse_ai_response(response_text)
        except RateLimitExceeded as e:
            logger.warning("Rate limit exceeded for suggestions user %s: %s", user_id, e)
            raise ValueError(f"AI suggestion rate limit exceeded: {str(e)}")
        except LLMProviderError as e:
            logger.error("All LLM providers failed for suggestions: %s", e)
            raise ValueError(f"AI suggestion generation failed: {str(e)}")
        except Exception as e:
            logger.error("AI suggestions failed: %s", e)
            raise ValueError(f"AI suggestion generation failed: {str(e)}")
    
    def _build_analysis_prompt(self, resume_content: str) -> str:
        """Build the prompt for resume analysis."""
        return f"""Analyze the following resume and provide a detailed analysis in JSON format.

Resume Content:
{resume_content}

Please provide your analysis in the following JSON format:
{{
    "overall_score": <number 0-100>,
    "strengths": [<list of 3-5 strengths>],
    "weaknesses": [<list of 3-5 weaknesses>],
    "suggestions": [<list of 5-7 specific suggestions>],
    "ats_compatibility": "<high, medium, or low>",
    "keywords_missing": [<list of important keywords missing>],
    "summary": "<2-3 sentence summary of the resume>"
}}

Provide only the JSON, no other text."""

    def _build_suggestions_prompt(self, resume_content: str, focus_area: str) -> str:
        """Build the prompt for specific suggestions."""
        return f"""Analyze this resume and provide detailed improvement suggestions focused on: {focus_area}

Resume Content:
{resume_content}

Provide your suggestions in JSON format:
{{
    "area_focus": "{focus_area}",
    "current_issues": [<list of issues in this area>],
    "specific_improvements": [<list of specific improvements>],
    "examples": [<examples of better phrasing if applicable>],
    "priority_improvements": [<top 5 priority improvements>],
    "quick_wins": [<quick changes with high impact>],
    "detailed_guidance": [<step-by-step guidance>]
}}

Provide only the JSON, no other text."""

    def _rule_based_scoring(self, content: str) -> Dict[str, Any]:
        "Simple rule-based fallback scoring for very short content."
        content_lower = content.lower().strip()
        score = 20  # Base score
        keywords = ['experience', 'skills', 'education', 'project', 'work', 'job', 'engineer', 'manager', 'developer']
        found_keywords = sum(1 for kw in keywords if kw in content_lower)
        score += found_keywords * 5
        score = min(100, max(0, score))
        logger.info(f"Rule-based score: {score} for content len {len(content)} with {found_keywords} keywords")
        return {
            "overall_score": score,
            "score": score,
            "strengths": ["Basic structure detected"],
            "weaknesses": ["Content too short for detailed analysis"],
            "suggestions": ["Add more details to experience, skills, education sections"],
            "ats_compatibility": "low",
            "keywords_missing": ["experience", "skills", "education"],
            "summary": "Basic rule-based analysis due to short content."
        }
    
    def _parse_ai_response(self, response_text: str) -> Dict[str, Any]:
        logger.info(f"Raw AI response length: {len(response_text)} chars")
        logger.debug(f"Raw response preview: {response_text[:500]}...")
        
        # Strip common wrappers like ```json
        cleaned = re.sub(r'```json|```|``` ?json', '', response_text, flags=re.IGNORECASE).strip()
        
        # Try multiple ways to extract JSON
        candidates = []
        for match in re.finditer(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', cleaned, re.DOTALL):
            candidates.append(match.group())
        
        if candidates:
            for json_str in candidates:
                try:
                    data = json.loads(json_str)
                    logger.info("JSON parsed successfully")
                    break
                except json.JSONDecodeError:
                    continue
            else:
                logger.warning("No valid JSON in candidates, trying repair")
                try:
                    from json_repair import repair_json
                    repaired = repair_json(cleaned)
                    data = json.loads(repaired)
                    logger.info("JSON repaired successfully")
                except ImportError:
                    logger.warning("json-repair not available")
                    data = {}
                except json.JSONDecodeError:
                    data = {}
        else:
            try:
                data = json.loads(cleaned)
            except json.JSONDecodeError:
                data = {}
        
        # Robust score extraction
        score_str = str(data.get("overall_score", 50))
        score = 50
        score_match = re.search(r'(\d+)', score_str)
        if score_match:
            score = int(score_match.group(1))
        score = min(100, max(0, score))
        
        result = {
            "overall_score": score,
            "score": score,
            "strengths": data.get("strengths", []),
            "weaknesses": data.get("weaknesses", []),
            "suggestions": data.get("suggestions", []),
            "ats_compatibility": data.get("ats_compatibility", "medium"),
            "keywords_missing": data.get("keywords_missing", []),
            "summary": data.get("summary", "Resume analysis completed.")
        }
        logger.info(f"Parsed score: {result['overall_score']}")
        return result


# Singleton instance
resume_analysis_service = ResumeAnalysisService()
