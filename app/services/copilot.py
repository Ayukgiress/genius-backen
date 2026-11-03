import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kanban import KanbanBoard, KanbanCard
from app.models.resume import Resume
from app.models.interview import Interview
from app.models.career_profile import CareerProfile
from app.models.event import Event
from app.crud import career_profile as career_profile_crud
from app.crud import resume as resume_crud
from app.crud import kanban as kanban_crud
from app.crud import interview as interview_crud
from app.crud import event as event_crud
from app.services import ai_analysis
from app.services.interview import interview_service

logger = logging.getLogger(__name__)


class CopilotService:
    async def get_next_actions(self, db: AsyncSession, user_id: int) -> List[Dict[str, Any]]:
        actions = []
        now = datetime.now(timezone.utc)
        
        # Get career profile
        profile = await career_profile_crud.get_career_profile_by_user(db, user_id)
        
        # Get resumes
        resumes = await resume_crud.get_resumes_by_user(db, user_id)
        if resumes:
            latest_resume = resumes[0]
            if latest_resume.score and latest_resume.score < 70:
                actions.append({
                    "id": f"fix_resume_{latest_resume.id}",
                    "type": "resume_improvement",
                    "title": "Improve your resume",
                    "description": f"Your resume score is {latest_resume.score}/100. Focus on keywords and impact statements.",
                    "priority": 9,
                    "reason": "Resume score below threshold",
                    "action": {"type": "analyze_resume", "resume_id": latest_resume.id},
                })
        
        # Get kanban data
        boards = await kanban_crud.get_boards_by_user(db, user_id)
        for board in boards:
            cards = await kanban_crud.get_cards_by_board(db, board.id)
            for card in cards:
                # Card in Applied for 7 days
                if card.status == "applied":
                    days_applied = (now - card.updated_at.replace(tzinfo=timezone.utc) if card.updated_at.tzinfo is None else now - card.updated_at).days
                    if days_applied >= 7:
                        actions.append({
                            "id": f"followup_{card.id}",
                            "type": "follow_up",
                            "title": f"Follow up on {card.title}",
                            "description": "It's been 7+ days since applying. Send a polite follow-up email.",
                            "priority": 8,
                            "reason": "Card sitting in Applied for 7 days",
                            "action": {"type": "create_letter", "card_id": card.id, "letter_type": "follow_up"},
                        })
                # New Interview card
                elif card.status == "interview":
                    actions.append({
                        "id": f"mock_{card.id}",
                        "type": "interview_prep",
                        "title": f"Prepare for {card.title} interview",
                        "description": "Start a mock interview session to practice.",
                        "priority": 10,
                        "reason": "New Interview card",
                        "action": {"type": "start_interview", "card_id": card.id},
                    })
                elif card.status == "offer":
                    actions.append({
                        "id": f"review_offer_{card.id}",
                        "type": "offer_review",
                        "title": f"Review offer for {card.title}",
                        "description": "Evaluate and respond to the offer.",
                        "priority": 9,
                        "reason": "Offer received",
                        "action": {"type": "review_offer", "card_id": card.id},
                    })
        
        # Get interviews
        interviews = await interview_crud.get_interviews_by_user(db, user_id)
        for interview in interviews:
            if interview.status in ["started", "active"]:
                actions.append({
                    "id": f"continue_interview_{interview.id}",
                    "type": "continue_interview",
                    "title": "Continue your interview practice",
                    "description": "Complete your in-progress interview session.",
                    "priority": 7,
                    "reason": "Interview in progress",
                    "action": {"type": "resume_interview", "interview_id": interview.id},
                })
        
        # Sort by priority
        actions.sort(key=lambda x: x["priority"], reverse=True)
        return actions
    
    async def chat(self, db: AsyncSession, user_id: int, message: str, history: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        history = history or []
        tool_calls = []
        response_text = ""
        
        message_lower = message.lower()
        
        # Tool calling based on intent
        if any(word in message_lower for word in ["search job", "find job", "look for job"]):
            try:
                from app.services.job_scraper import job_service
                jobs = await job_service.search_jobs({"query": message}, limit=5)
                tool_calls.append({
                    "tool": "search_jobs",
                    "args": {"query": message},
                    "result": {"count": len(jobs) if jobs else 0}
                })
                response_text = f"I found {len(jobs) if jobs else 0} job opportunities related to your search. "
            except Exception as e:
                logger.error(f"Job search failed: {e}")
                response_text = "I tried to search for jobs but encountered an issue. "
        elif any(word in message_lower for word in ["analyze resume", "resume feedback"]):
            resumes = await resume_crud.get_resumes_by_user(db, user_id)
            if resumes:
                tool_calls.append({
                    "tool": "analyze_resume",
                    "args": {"resume_id": resumes[0].id},
                    "result": {"resume_id": resumes[0].id, "score": resumes[0].score}
                })
                response_text = f"I can analyze your latest resume (score: {resumes[0].score or 'N/A'}). "
            else:
                response_text = "You don't have any resumes uploaded yet. "
        elif any(word in message_lower for word in ["cover letter", "create letter"]):
            tool_calls.append({
                "tool": "create_letter",
                "args": {"type": "cover_letter"},
                "result": {"status": "ready"}
            })
            response_text = "I can help create a cover letter. "
        elif any(word in message_lower for word in ["kanban", "card", "add job"]):
            tool_calls.append({
                "tool": "create_kanban_card",
                "args": {"status": "todo"},
                "result": {"status": "ready"}
            })
            response_text = "I can help you add a job to your kanban board. "
        elif any(word in message_lower for word in ["interview", "practice", "mock"]):
            tool_calls.append({
                "tool": "start_interview",
                "args": {},
                "result": {"status": "ready"}
            })
            response_text = "I can start a mock interview session for you. "
        else:
            # Use LLM for general conversation if available
            try:
                if interview_service.groq_client:
                    actions = await self.get_next_actions(db, user_id)
                    system_prompt = f"You are a helpful career coach assistant. Here are the user's top priorities: {[a['title'] for a in actions[:3]]}. Be concise and actionable."
                    response = await interview_service.groq_client.chat.completions.create(
                        model="llama-3.3-70b-versatile",
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": message}
                        ],
                        temperature=0.7,
                        max_tokens=500,
                    )
                    response_text = response.choices[0].message.content
                else:
                    response_text = "I'm here to help with your job search. What can I assist you with?"
            except Exception as e:
                logger.error(f"Chat LLM failed: {e}")
                response_text = "I'm here to help with your job search. I can search jobs, analyze resumes, create cover letters, manage your kanban board, and start mock interviews."
        
        actions = await self.get_next_actions(db, user_id)
        return {
            "response": response_text,
            "tool_calls": tool_calls,
            "suggestions": actions[:3],
            "sources": []
        }
    
    async def generate_weekly_summary(self, db: AsyncSession, user_id: int) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        week_start = now - timedelta(days=7)
        week_end = now
        
        # Count applications (cards moved to applied)
        boards = await kanban_crud.get_boards_by_user(db, user_id)
        applications_count = 0
        for board in boards:
            cards = await kanban_crud.get_cards_by_board(db, board.id)
            for card in cards:
                if card.status in ["applied"] and card.updated_at:
                    card_updated = card.updated_at.replace(tzinfo=timezone.utc) if card.updated_at.tzinfo is None else card.updated_at
                    if card_updated >= week_start:
                        applications_count += 1
        
        # Count interviews
        interviews = await interview_crud.get_interviews_by_user(db, user_id)
        interviews_count = 0
        for i in interviews:
            if i.created_at:
                interview_created = i.created_at.replace(tzinfo=timezone.utc) if hasattr(i.created_at, 'tzinfo') and i.created_at.tzinfo is None else i.created_at
                if interview_created >= week_start:
                    interviews_count += 1
        
        # Score changes
        resumes = await resume_crud.get_resumes_by_user(db, user_id)
        score_changes = []
        if len(resumes) >= 2:
            score_changes.append({
                "type": "resume_score",
                "old": resumes[1].score,
                "new": resumes[0].score,
                "change": (resumes[0].score or 0) - (resumes[1].score or 0)
            })
        
        # Goal for next week
        actions = await self.get_next_actions(db, user_id)
        if actions:
            goal_next_week = f"Focus on: {actions[0]['title']}"
        else:
            goal_next_week = "Apply to 5 quality positions and complete 2 mock interviews"
        
        return {
            "user_id": user_id,
            "week_start": week_start,
            "week_end": week_end,
            "applications_count": applications_count,
            "interviews_count": interviews_count,
            "score_changes": score_changes,
            "goal_next_week": goal_next_week,
            "highlights": [f"Applied to {applications_count} positions", f"Completed {interviews_count} interviews this week"],
            "created_at": now
        }


copilot_service = CopilotService()
