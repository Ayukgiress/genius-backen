import google.genai as genai
import json
import re
from typing import Dict, Any, Optional
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

MAX_RESUME_LENGTH = 50000  


class ResumeAnalysisService:
    """Service for analyzing resumes using Google Gemini AI"""
    
    def __init__(self):
        if settings.GEMINI_API_KEY:
            self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
            self.model_name = "gemini-1.5-flash"
        else:
            self.client = None
            self.model_name = None
    
    async def analyze_resume(self, resume_content: str) -> Dict[str, Any]:
        """
        Analyze a resume and provide suggestions using Gemini AI.
        
        Args:
            resume_content: The text content of the resume
            
        Returns:
            Dict containing analysis results with:
            - overall_score: int (0-100)
            - strengths: list of strings
            - weaknesses: list of strings
            - suggestions: list of strings
            - ats_compatibility: str (high/medium/low)
            - keywords_missing: list of strings
            - summary: str
        """
        if not self.client:
            raise ValueError("GEMINI_API_KEY not configured")
        
        if len(resume_content) > MAX_RESUME_LENGTH:
            raise ValueError(f"Resume content exceeds maximum length of {MAX_RESUME_LENGTH} characters")
        
        if not resume_content or not resume_content.strip():
            raise ValueError("Resume content cannot be empty")
        
        prompt = self._build_analysis_prompt(resume_content)
        
        try:
            logger.info(f"Starting AI resume analysis with model {self.model_name}")
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            logger.info("AI resume analysis completed successfully")
            analysis_result = self._parse_ai_response(response.text)
            return analysis_result
        except ValueError:
            raise  # Re-raise ValueError as-is
        except Exception as e:
            logger.error(f"AI resume analysis failed: {str(e)}", exc_info=True)
            raise
    
    def _build_analysis_prompt(self, resume_content: str) -> str:
        """Build the prompt for resume analysis"""
        return f"""You are an expert resume reviewer and career consultant. 
Analyze the following resume and provide detailed feedback in JSON format.

Resume Content:
{resume_content}

Provide your analysis in the following JSON format only (no other text):
{{
    "overall_score": <number between 0-100>,
    "strengths": [<list of 3-5 strengths>],
    "weaknesses": [<list of 3-5 weaknesses>],
    "suggestions": [<list of 5-7 specific improvement suggestions>],
    "ats_compatibility": "<high, medium, or low>",
    "keywords_missing": [<list of important keywords that could be added>],
    "summary": "<2-3 sentence overall summary>"
}}

Be critical but constructive. Consider:
- Formatting and structure
- Content clarity and conciseness
- Action verbs and quantifiable achievements
- Keywords for ATS (Applicant Tracking Systems)
- Industry relevance
- Missing sections or information"""

    def _parse_ai_response(self, response_text: str) -> Dict[str, Any]:
        """Parse the AI response into a structured dictionary"""
        
        # Try to extract JSON from the response
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        
        if json_match:
            try:
                result = json.loads(json_match.group())
                return self._validate_and_normalize(result)
            except json.JSONDecodeError:
                pass
        
        # If JSON parsing fails, create a structured response from the text
        return {
            "overall_score": 50,
            "strengths": ["Unable to parse AI response"],
            "weaknesses": ["Parse error"],
            "suggestions": ["Please try again"],
            "ats_compatibility": "unknown",
            "keywords_missing": [],
            "summary": "Error parsing AI response. Please try again."
        }
    
    def _validate_and_normalize(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and normalize the analysis result"""
        return {
            "overall_score": min(max(result.get("overall_score", 50), 0), 100),
            "strengths": result.get("strengths", []),
            "weaknesses": result.get("weaknesses", []),
            "suggestions": result.get("suggestions", []),
            "ats_compatibility": result.get("ats_compatibility", "unknown"),
            "keywords_missing": result.get("keywords_missing", []),
            "summary": result.get("summary", "")
        }
    
    async def generate_suggestions(self, resume_content: str, focus_area: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate specific suggestions for improving a resume.
        
        Args:
            resume_content: The text content of the resume
            focus_area: Optional specific area to focus on (e.g., 'summary', 'experience', 'skills')
            
        Returns:
            Dict containing targeted suggestions
        """
        if not self.client:
            raise ValueError("GEMINI_API_KEY not configured")
        
        if len(resume_content) > MAX_RESUME_LENGTH:
            raise ValueError(f"Resume content exceeds maximum length of {MAX_RESUME_LENGTH} characters")
        
        if focus_area:
            prompt = f"""You are an expert resume reviewer. Provide specific suggestions for improving the {focus_area} section of this resume.

Resume Content:
{resume_content}

Provide your suggestions in JSON format:
{{
    "focus_area": "{focus_area}",
    "current_issues": [<list of current issues in this section>],
    "specific_suggestions": [<list of 3-5 specific suggestions>],
    "examples": [<optional examples of improvements>]
}}"""
        else:
            prompt = f"""You are an expert resume reviewer. Provide general improvement suggestions for this resume.

Resume Content:
{resume_content}

Provide your suggestions in JSON format:
{{
    "priority_improvements": [<list of top 5 priority improvements>],
    "quick_wins": [<list of quick changes with high impact>],
    "detailed_guidance": [<step-by-step guidance>]
}}"""
        
        try:
            logger.info(f"Generating AI suggestions for focus_area={focus_area}")
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            logger.info("AI suggestions generated successfully")
            return self._parse_ai_response(response.text)
        except ValueError:
            raise  # Re-raise ValueError as-is
        except Exception as e:
            logger.error(f"AI suggestion generation failed: {str(e)}", exc_info=True)
            raise


# Singleton instance
resume_analysis_service = ResumeAnalysisService()
