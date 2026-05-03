import json
import re
from typing import Dict, Any, Optional
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

MAX_RESUME_LENGTH = 50000


class ResumeAnalysisService:
    """Service for analyzing resumes using Groq AI (free tier)"""
    
    def __init__(self):
        self.groq_client = None
        self.gemini_client = None
        self.model_name = None
        self.provider = None
        
        if settings.GROQ_API_KEY:
            try:
                from groq import AsyncGroq
                self.groq_client = AsyncGroq(api_key=settings.GROQ_API_KEY)
                self.model_name = "llama-3.3-70b-versatile"
                self.provider = "groq"
                logger.info(f"Using Groq for AI analysis (free tier) with model {self.model_name}")
            except ImportError:
                logger.warning("Groq package not installed")
        
        if settings.GEMINI_API_KEY and not self.groq_client:
            try:
                import google.genai as genai
                self.gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
                self.model_name = "gemini-2.0-flash"
                self.provider = "gemini"
                logger.info(f"Using Gemini for AI analysis with model {self.model_name}")
            except ImportError:
                logger.warning("Google GenAI package not installed")
    
    async def analyze_resume(self, resume_content: str) -> Dict[str, Any]:
        """
        Analyze a resume and provide suggestions using AI.
        """
        if not self.groq_client and not self.gemini_client:
            raise ValueError("No AI provider configured. Please set GROQ_API_KEY or GEMINI_API_KEY")
        
        if len(resume_content) > MAX_RESUME_LENGTH:
            raise ValueError(f"Resume content exceeds maximum length of {MAX_RESUME_LENGTH} characters")
        
        if len(resume_content.strip()) < 50:
            logger.warning(f"Resume content very short ({len(resume_content.strip())} chars), using fallback scoring")
            return self._rule_based_scoring(resume_content)
        
        if len(resume_content) > MAX_RESUME_LENGTH:
            raise ValueError(f"Resume content exceeds maximum length of {MAX_RESUME_LENGTH} characters")
        
        prompt = self._build_analysis_prompt(resume_content)
        
        # Try Groq first (free)
        if self.groq_client:
            try:
                logger.info(f"Starting AI resume analysis with Groq model {self.model_name}")
                response = await self.groq_client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": "You are a professional resume analyst. Provide detailed analysis in JSON format. The overall_score MUST be an integer between 0 and 100."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,
                    max_tokens=4000,
                    response_format={"type": "json_object"}
                )
                logger.info("AI resume analysis completed successfully with Groq")
                return self._parse_ai_response(response.choices[0].message.content)
            except Exception as groq_error:
                logger.warning(f"Groq failed, trying Gemini: {groq_error}")
        
        if self.gemini_client:
            try:
                model = "gemini-2.0-flash"
                logger.info(f"Starting AI resume analysis with Gemini model {model}")
                response = self.gemini_client.models.generate_content(
                    model=model,
                    contents=prompt
                )
                logger.info("AI resume analysis completed successfully with Gemini")
                return self._parse_ai_response(response.text)
            except Exception as gemini_error:
                logger.error(f"Gemini also failed: {gemini_error}")
                raise ValueError(f"AI analysis failed: {str(gemini_error)}")
        
        raise ValueError("No AI provider available or all providers failed")
    
    async def get_suggestions(self, resume_content: str, focus_area: str = "general") -> Dict[str, Any]:
        """Get AI suggestions for improving a specific area of the resume."""
        if not self.groq_client and not self.gemini_client:
            raise ValueError("No AI provider configured")
        
        prompt = self._build_suggestions_prompt(resume_content, focus_area)
        
        if self.groq_client:
            try:
                logger.info(f"Generating AI suggestions with Groq for focus_area={focus_area}")
                response = await self.groq_client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": "You are a professional resume coach. Provide detailed suggestions in JSON format."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,
                    max_tokens=4000,
                    response_format={"type": "json_object"}
                )
                logger.info("AI suggestions generated successfully with Groq")
                return self._parse_ai_response(response.choices[0].message.content)
            except Exception as groq_error:
                logger.warning(f"Groq failed for suggestions, trying Gemini: {groq_error}")
        
        # Fallback to Gemini
        if self.gemini_client:
            try:
                logger.info(f"Generating AI suggestions with Gemini for focus_area={focus_area}")
                response = self.gemini_client.models.generate_content(
                    model=self.model_name,
                    contents=prompt
                )
                logger.info("AI suggestions generated successfully with Gemini")
                return self._parse_ai_response(response.text)
            except Exception as gemini_error:
                logger.error(f"Gemini also failed for suggestions: {gemini_error}")
                raise ValueError(f"AI suggestion generation failed: {str(gemini_error)}")
        
        raise ValueError("No AI provider available")
    
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
