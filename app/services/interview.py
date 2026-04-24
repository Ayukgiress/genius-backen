import json
import logging
from typing import Dict, Any, List, Optional
from app.core.config import settings
from app.services.job_scraper import job_service

logger = logging.getLogger(__name__)

class InterviewService:
    """Service for managing AI-powered job interviews using Groq"""

    def __init__(self):
        self.groq_client = None
        if settings.GROQ_API_KEY:
            try:
                from groq import AsyncGroq
                self.groq_client = AsyncGroq(api_key=settings.GROQ_API_KEY)
                logger.info("InterviewService initialized with Groq client")
            except ImportError:
                logger.warning("Groq package not installed for InterviewService")

    async def start_interview(self, job_id: str, resume_content: Optional[str] = None) -> Dict[str, Any]:
        """
        Start a new AI interview for a specific job.
        Returns the initial AI message to begin the conversation.
        """
        if not self.groq_client:
            raise ValueError("Groq client not configured. Please set GROQ_API_KEY")

        # Get job details
        job = await job_service.match_with_resume(job_id, resume_content or "")
        if not job:
            raise ValueError(f"Job with ID {job_id} not found")

        # Convert JobMatchResponse to dict for compatibility
        job_dict = {
            "title": job.title,
            "company": job.company,
            "description": job.description or "",
            "requirements": job.requirements or "",
        }

        # Build initial interview prompt
        system_prompt = self._build_interview_system_prompt(job_dict, resume_content)

        # Generate initial AI question
        response = await self.groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Please start the interview by asking the first question."}
            ],
            temperature=0.7,
            max_tokens=1000
        )

        initial_message = response.choices[0].message.content

        return {
            "initial_message": initial_message,
            "job_title": job.get("title", "Unknown Position"),
            "company": job.get("company", "Unknown Company")
        }

    async def continue_interview(self, conversation_history: List[Dict[str, str]], job_id: str, resume_content: Optional[str] = None) -> str:
        """
        Continue an ongoing interview with the user's response.
        """
        if not self.groq_client:
            raise ValueError("Groq client not configured")

        # Get job details for context
        job = await job_service.match_with_resume(job_id, resume_content or "")
        if not job:
            raise ValueError(f"Job with ID {job_id} not found")

        # Convert JobMatchResponse to dict for compatibility
        job_dict = {
            "title": job.title,
            "company": job.company,
            "description": job.description or "",
            "requirements": job.requirements or "",
        }

        # Build system prompt with job context
        system_prompt = self._build_interview_system_prompt(job_dict, resume_content)

        # Prepare messages for Groq API (limit to last 10 messages to avoid token limits)
        messages = [{"role": "system", "content": system_prompt}]
        recent_history = conversation_history[-10:] if len(conversation_history) > 10 else conversation_history

        for msg in recent_history:
            messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })

        response = await self.groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.7,
            max_tokens=1000
        )

        return response.choices[0].message.content

    def _build_interview_system_prompt(self, job: Dict[str, Any], resume_content: Optional[str] = None) -> str:
        """Build the system prompt for the AI interviewer"""
        job_title = job.get("title", "Unknown Position")
        company = job.get("company", "Unknown Company")
        description = job.get("description", "")
        requirements = job.get("requirements", "")

        prompt = f"""You are an experienced hiring manager conducting a job interview for the position of {job_title} at {company}.

Job Details:
Title: {job_title}
Company: {company}
Description: {description}
Requirements: {requirements}

Your role is to conduct a professional, structured interview that assesses the candidate's:
1. Technical skills relevant to the job
2. Experience and background
3. Problem-solving abilities
4. Communication skills
5. Cultural fit

Guidelines for the interview:
- Ask 1 question at a time
- Keep questions relevant to the job requirements
- Start with introductory questions, then move to technical questions
- Be encouraging and professional
- Provide brief feedback when appropriate
- End the interview when you have sufficient information (typically 5-8 questions)

"""

        if resume_content:
            prompt += f"\nCandidate's Resume Context:\n{resume_content[:2000]}...\n\nUse this resume information to tailor your questions to the candidate's background."

        prompt += "\n\nRespond naturally as an interviewer would. Ask follow-up questions based on the candidate's responses."

        return prompt


# Singleton instance
interview_service = InterviewService()