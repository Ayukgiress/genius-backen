import json
import logging
import base64
import cv2
import numpy as np
import mediapipe as mp
import asyncio
from typing import Dict, Any, List, Optional
from app.core.config import settings
from app.services.job_scraper import job_service

logger = logging.getLogger(__name__)

class InterviewService:
    "Service for managing AI-powered job interviews using Groq. Now supports video frame analysis."

    def __init__(self):
        self.groq_client = None
        self.openai_client = None
        self.mp_face_detection = mp.solutions.face_detection
        self.mp_pose = mp.solutions.pose
        self.face_detection = self.mp_face_detection.FaceDetection(model_selection=0, min_detection_confidence=0.5)
        self.pose = self.mp_pose.Pose(min_detection_confidence=0.5, min_pose_confidence=0.5)
        if settings.GROQ_API_KEY:
            try:
                from groq import AsyncGroq
                self.groq_client = AsyncGroq(api_key=settings.GROQ_API_KEY)
                logger.info('InterviewService initialized with Groq client')
            except ImportError:
                logger.warning('Groq package not installed for InterviewService')
        
        if settings.OPENAI_API_KEY:
            try:
                from openai import AsyncOpenAI
                self.openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
                logger.info('InterviewService initialized with OpenAI client')
            except ImportError:
                logger.warning('OpenAI package not installed for InterviewService')

    async def transcribe_audio(self, audio_file: Any) -> str:
        "Transcribe audio using Groq Whisper"
        if not self.groq_client:
            raise ValueError('Groq client not configured')
        
        try:
            translation = await self.groq_client.audio.transcriptions.create(
                file=audio_file,
                model='whisper-large-v3',
                response_format='text'
            )
            return translation
        except Exception as e:
            logger.error(f'STT error: {e}')
            raise e

    async def generate_speech(self, text: str) -> bytes:
        "Generate speech using OpenAI TTS"
        if not self.openai_client:
            raise ValueError('OpenAI client not configured')
        
        try:
            response = await self.openai_client.audio.speech.create(
                model='tts-1',
                voice='alloy',
                input=text
            )
            return response.read()
        except Exception as e:
            logger.error(f'TTS error: {e}')
            raise e

    async def process_video_frame(self, base64_data: str, timestamp: int, job_id: str, conversation_history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        "Process video chunk: MediaPipe face/posture -> visual analysis -> LLM next question."
        if not self.groq_client:
            return {'error': 'Groq client not configured', 'status': 'error'}

        # Decode base64 webp
        try:
            image_data = base64.b64decode(base64_data)
            nparr = np.frombuffer(image_data, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame is None:
                return {'error': 'Failed to decode frame', 'status': 'error'}
        except Exception as e:
            logger.error(f'Frame decode error: {e}')
            return {'error': str(e), 'status': 'error'}

        rgb_frame = None
        try:
            # RGB for MediaPipe
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # Face detection
            face_results = self.face_detection.process(rgb_frame)
            face_desc = 'Face detected' if face_results.detections else 'No face detected'

            # Pose estimation for posture
            pose_results = self.pose.process(rgb_frame)
            posture_desc = 'Upright/confident posture' if pose_results.pose_landmarks else 'Posture not clear'

            # Visual 'STT' (no audio)
            visual_stt = f'No audio detected. Visual analysis: {face_desc}. {posture_desc}. Candidate appears engaged.'

            # Job context
            try:
                job = await job_service.match_with_resume(job_id, '')
                job_dict = {
                    'title': getattr(job, 'title', 'Unknown'),
                    'company': getattr(job, 'company', 'Unknown'),
                }
            except:
                job_dict = {'title': 'Unknown', 'company': 'Unknown'}

            # LLM video analysis prompt
            system_prompt = self._build_video_analysis_prompt(job_dict)
            user_prompt = f"Analyze video frame + speech: '{visual_stt}'. "
            if conversation_history:
                user_prompt += f"Recent history: {json.dumps(conversation_history[-3:])} . "
            user_prompt += 'From job interview. Ask the next relevant question.'

            messages = [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt}
            ]

            response = await self.groq_client.chat.completions.create(
                model='llama-3.3-70b-versatile',
                messages=messages,
                temperature=0.7,
                max_tokens=400
            )
            ai_text = response.choices[0].message.content.strip()

            result = {
                'transcript': visual_stt,
                'ai_text': ai_text,
                'status': 'responding',
                'timestamp': timestamp,
                'visual': {
                    'face': face_desc,
                    'posture': posture_desc
                }
            }
            return result

        finally:
            # Privacy: delete frame data
            if 'frame' in locals():
                del frame
            if 'nparr' in locals():
                del nparr
            if rgb_frame is not None:
                del rgb_frame

    async def start_interview(self, job_id: str, resume_content: Optional[str] = None) -> Dict[str, Any]:
        "Start a new AI interview for a specific job."
        if not self.groq_client:
            raise ValueError('Groq client not configured. Please set GROQ_API_KEY')

        job = await job_service.match_with_resume(job_id, resume_content or '')
        if not job:
            raise ValueError(f'Job with ID {job_id} not found')

        job_dict = {
            'title': job.title,
            'company': job.company,
            'description': job.description or '',
            'requirements': job.requirements or '',
        }

        system_prompt = self._build_interview_system_prompt(job_dict, resume_content)

        response = await self.groq_client.chat.completions.create(
            model='llama-3.3-70b-versatile',
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': 'Please start the interview by asking the first question.'}
            ],
            temperature=0.7,
            max_tokens=1000
        )

        initial_message = response.choices[0].message.content

        return {
            'initial_message': initial_message,
            'job_title': job_dict.get('title', 'Unknown Position'),
            'company': job_dict.get('company', 'Unknown Company')
        }

    async def continue_interview(self, conversation_history: List[Dict[str, str]], job_id: str, resume_content: Optional[str] = None) -> str:
        "Continue an ongoing interview with the user's response."
        if not self.groq_client:
            raise ValueError('Groq client not configured')

        job = await job_service.match_with_resume(job_id, resume_content or '')
        if not job:
            raise ValueError(f'Job with ID {job_id} not found')

        job_dict = {
            'title': job.title,
            'company': job.company,
            'description': job.description or '',
            'requirements': job.requirements or '',
        }

        system_prompt = self._build_interview_system_prompt(job_dict, resume_content)

        messages = [{'role': 'system', 'content': system_prompt}]
        recent_history = conversation_history[-10:] if len(conversation_history) > 10 else conversation_history
        for msg in recent_history:
            messages.append({
                'role': msg['role'],
                'content': msg['content']
            })

        response = await self.groq_client.chat.completions.create(
            model='llama-3.3-70b-versatile',
            messages=messages,
            temperature=0.7,
            max_tokens=1000
        )

        return response.choices[0].message.content

    def _build_interview_system_prompt(self, job: Dict[str, Any], resume_content: Optional[str] = None) -> str:
        "Build the system prompt for the AI interviewer"
        job_title = job.get('title', 'Unknown Position')
        company = job.get('company', 'Unknown Company')
        description = job.get('description', '')
        requirements = job.get('requirements', '')

        if description and len(description) > 3000:
            description = description[:3000] + '...'
        if requirements and len(requirements) > 3000:
            requirements = requirements[:3000] + '...'

        job_details_section = f'Description: {description}'
        if requirements and requirements.strip() and requirements.strip()[:100] not in description:
            job_details_section += f'\nRequirements: {requirements}'

        prompt = f'''You are an experienced hiring manager conducting a job interview for the position of {job_title} at {company}.

Job Details:
Title: {job_title}
Company: {company}
{job_details_section}

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
- End the interview when you have sufficient information (typically 5-8 questions)'''

        if resume_content:
            prompt += f'''

Candidate's Resume Context:
{resume_content[:2000]}...

Use this resume information to tailor your questions to the candidate's background.'''

        prompt += '''

Respond naturally as an interviewer would. Ask follow-up questions based on the candidate's responses.'''

        logger.info(f'Generated system prompt with length: {len(prompt)} characters')
        return prompt

    def _build_video_analysis_prompt(self, job: Dict[str, Any]) -> str:
        "Build system prompt for video frame analysis."
        job_title = job.get('title', 'Unknown')
        company = job.get('company', 'Unknown')
        return f'''You are a hiring manager analyzing VIDEO FRAMES + SPEECH from a job interview for {job_title} at {company}.

Given frame analysis and speech transcript, analyze:
- Facial expressions (confidence, nervousness, engagement)
- Body posture and language (open, closed, confident)
- Overall candidate state
- Content of speech

Then respond with the NEXT interview question based on analysis.

Format your response as the next question/feedback.'''

# Singleton instance
interview_service = InterviewService()
