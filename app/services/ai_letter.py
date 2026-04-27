import json
from typing import Optional
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

class LetterGenerationService:
    """Service for generating custom letters using AI"""

    def __init__(self):
        self.groq_client = None
        self.gemini_client = None

        if settings.GROQ_API_KEY:
            try:
                from groq import AsyncGroq
                self.groq_client = AsyncGroq(api_key=settings.GROQ_API_KEY)
                logger.info("Using Groq for letter generation")
            except ImportError:
                logger.warning("Groq package not installed")

        if settings.GEMINI_API_KEY:
            try:
                import google.genai as genai
                self.gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
                logger.info("Using Gemini for letter generation")
            except ImportError:
                logger.warning("Google GenAI package not installed")

    async def generate_letter(
        self,
        job_title: str,
        company_name: str,
        recipient_name: Optional[str] = None,
        resume_content: str = "",
        letter_type: str = "cover_letter",
        custom_instructions: Optional[str] = None
    ) -> str:
        """
        Generate a custom letter using AI.
        """
        if not self.groq_client and not self.gemini_client:
            raise ValueError("No AI provider configured. Please set GROQ_API_KEY or GEMINI_API_KEY")

        prompt = self._build_letter_prompt(
            job_title=job_title,
            company_name=company_name,
            recipient_name=recipient_name,
            resume_content=resume_content,
            letter_type=letter_type,
            custom_instructions=custom_instructions
        )

        try:
            if self.groq_client:
                return await self._generate_with_groq(prompt)
            elif self.gemini_client:
                return await self._generate_with_gemini(prompt)
        except Exception as e:
            logger.error(f"AI letter generation failed: {str(e)}")
            raise

    def _build_letter_prompt(
        self,
        job_title: str,
        company_name: str,
        recipient_name: Optional[str],
        resume_content: str,
        letter_type: str,
        custom_instructions: Optional[str]
    ) -> str:
        """Build the AI prompt for letter generation."""

        letter_type_descriptions = {
            "cover_letter": "a professional cover letter",
            "thank_you": "a thank you letter following a job interview",
            "networking": "a networking or introduction letter",
            "follow_up": "a follow-up letter after applying for a job",
        }

        letter_description = letter_type_descriptions.get(letter_type, "a professional letter")

        prompt = f"""Generate {letter_description} for the position of {job_title} at {company_name}.

Recipient: {recipient_name or "Hiring Manager"}

"""

        if resume_content:
            prompt += f"""
Based on this resume content:
{resume_content[:2000]}  # Truncate for token limits

"""

        if custom_instructions:
            prompt += f"""
Additional instructions: {custom_instructions}

"""

        prompt += """
Please write a compelling, professional letter that:
- Highlights relevant skills and experience
- Shows enthusiasm for the role and company
- Is concise and well-structured
- Uses proper business letter format

Return only the letter content, no additional explanations."""

        return prompt

    async def _generate_with_groq(self, prompt: str) -> str:
        """Generate letter using Groq."""
        try:
            response = await self.groq_client.chat.completions.create(
                model="mixtral-8x7b-32768",
                messages=[
                    {"role": "system", "content": "You are a professional career counselor and letter writer."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=2000,
                temperature=0.7
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Groq API error: {str(e)}")
            raise ValueError(f"Failed to generate letter with Groq: {str(e)}")

    async def _generate_with_gemini(self, prompt: str) -> str:
        """Generate letter using Gemini."""
        try:
            response = await self.gemini_client.models.generate_content(
                model="gemini-1.5-flash",
                contents=prompt,
                config={
                    "max_output_tokens": 2000,
                    "temperature": 0.7
                }
            )
            return response.text.strip()
        except Exception as e:
            logger.error(f"Gemini API error: {str(e)}")
            raise ValueError(f"Failed to generate letter with Gemini: {str(e)}")

# Create singleton instance
letter_generation_service = LetterGenerationService()