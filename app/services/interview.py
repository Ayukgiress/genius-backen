import json
import logging
import base64
import io
try:
    import cv2
    import numpy as np
    import mediapipe as mp
except ImportError:
    cv2 = None
    np = None
    mp = None
try:
    import ffmpeg
    from pydub import AudioSegment
except ImportError:
    ffmpeg = None
    AudioSegment = None
import asyncio
import functools
from typing import Dict, Any, List, Optional
from app.core.config import settings
from app.services.job_scraper import job_service

logger = logging.getLogger(__name__)

class InterviewService:
    "Service for managing AI-powered job interviews using Groq. Now supports video frame analysis."

    def __init__(self):
        self.groq_client = None
        self.openai_client = None
        self.elevenlabs_client = None
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

        if settings.ELEVENLABS_API_KEY:
            try:
                from elevenlabs import AsyncElevenLabs
                self.elevenlabs_client = AsyncElevenLabs(api_key=settings.ELEVENLABS_API_KEY)
                logger.info('InterviewService initialized with ElevenLabs client')
            except ImportError:
                logger.warning('ElevenLabs package not installed for InterviewService')

    async def transcribe_audio(self, audio_file: Any) -> str:
        "Transcribe audio using Groq Whisper"
        if not self.groq_client:
            raise ValueError('Groq client not configured')

        try:
            filename = getattr(audio_file, 'name', 'audio.webm')
            # Read the bytes so we can pass them properly
            audio_bytes = audio_file.read()
            
            if not audio_bytes or len(audio_bytes) < 100:
                logger.warning(f"Audio too small to transcribe: {len(audio_bytes) if audio_bytes else 0} bytes")
                return ""

            # Groq needs (filename, bytes, mimetype) tuple
            if filename.endswith('.wav'):
                content_type = "audio/wav"
            else:
                content_type = "audio/webm"
                filename = "audio.webm"

            translation = await self.groq_client.audio.transcriptions.create(
                file=(filename, audio_bytes, content_type),
                model='whisper-large-v3',
                response_format='text'
            )
            return translation if translation else ""
        except Exception as e:
            # Handle common Whisper errors that should not crash the interview
            error_msg = str(e).lower()
            if "could not process file" in error_msg or "invalid_request_error" in error_msg:
                logger.warning(f"Whisper rejected audio: {e}")
                return ""
            
            logger.error(f'STT error: {e}')
            raise e

    async def generate_speech(self, text: str) -> bytes:
        "Generate speech using ElevenLabs, OpenAI, or pyttsx3 as fallback"
        # Try ElevenLabs first
        if self.elevenlabs_client:
            try:
                logger.info(f"Generating speech with ElevenLabs for text: {text[:50]}...")
                from elevenlabs import VoiceSettings
                audio_stream = await self.elevenlabs_client.generate(
                    text=text,
                    voice="Rachel",  # Professional female voice
                    model_id="eleven_monolingual_v1",
                    voice_settings=VoiceSettings(
                        stability=0.5,
                        similarity_boost=0.8,
                        style=0.5,
                        use_speaker_boost=True
                    )
                )
                audio_data = b""
                async for chunk in audio_stream:
                    audio_data += chunk
                
                if audio_data:
                    logger.info(f"ElevenLabs TTS successful, generated {len(audio_data)} bytes")
                    return audio_data
                else:
                    logger.warning("ElevenLabs generated empty audio")
            except Exception as e:
                logger.warning(f'ElevenLabs TTS failed: {e}')

        # Try OpenAI TTS
        if self.openai_client:
            try:
                logger.info(f"Generating speech with OpenAI for text: {text[:50]}...")
                response = await self.openai_client.audio.speech.create(
                    model="tts-1",
                    voice="alloy",
                    input=text
                )
                audio_data = b""
                async for chunk in response.aiter_bytes():
                    audio_data += chunk
                
                if audio_data:
                    logger.info(f"OpenAI TTS successful, generated {len(audio_data)} bytes")
                    return audio_data
                else:
                    logger.warning("OpenAI generated empty audio")
            except Exception as e:
                logger.warning(f'OpenAI TTS failed: {e}')

        # Fallback to pyttsx3
        logger.info(f"Falling back to pyttsx3 TTS for text: {text[:50]}...")
        import pyttsx3
        import tempfile
        import os

        def _generate_audio():
            try:
                engine = pyttsx3.init()
                # Set properties if needed
                engine.setProperty('rate', 180)  # Speed
                engine.setProperty('volume', 0.9)  # Volume

                with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
                    temp_path = temp_file.name

                engine.save_to_file(text, temp_path)
                engine.runAndWait()

                with open(temp_path, 'rb') as f:
                    audio_data = f.read()
                return audio_data
            except Exception as py_error:
                logger.error(f"pyttsx3 inner error: {py_error}")
                raise py_error
            finally:
                if 'temp_path' in locals():
                    try:
                        os.unlink(temp_path)
                    except:
                        pass

        try:
            audio_data = await asyncio.to_thread(_generate_audio)
            if audio_data:
                logger.info(f"pyttsx3 TTS successful, generated {len(audio_data)} bytes")
                return audio_data
            else:
                logger.warning("pyttsx3 generated empty audio")
                raise ValueError("pyttsx3 generated empty audio")
        except Exception as e:
            logger.error(f'pyttsx3 TTS error: {e}')
            raise e

    async def text_to_speech_base64(self, text: str) -> Optional[str]:
        """Convert text to speech and return as base64 encoded string."""
        try:
            # Generate speech from AI response
            speech_bytes = await self.generate_speech(text)

            # Try to convert speech to MP3 if libraries are available
            if AudioSegment is not None:
                try:
                    # Convert speech to MP3
                    speech_segment = AudioSegment.from_file(io.BytesIO(speech_bytes), format="wav")  # TTS generates WAV
                    mp3_buffer = io.BytesIO()
                    speech_segment.export(mp3_buffer, format="mp3")
                    audio_data_final = mp3_buffer.getvalue()
                except Exception as conv_error:
                    logger.warning(f"Audio conversion failed: {conv_error}, using WAV directly")
                    audio_data_final = speech_bytes
            else:
                logger.warning("Audio processing libraries not available, using WAV directly")
                audio_data_final = speech_bytes

            # Encode to base64
            return base64.b64encode(audio_data_final).decode("utf-8")
        except Exception as e:
            logger.error(f"Text-to-speech conversion error: {e}")
            return None

    async def process_audio_chunk(self, base64_audio: str, job_id: str, conversation_history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        "Process audio chunk: decode base64 WebM/Opus -> STT -> AI response -> TTS (optional) -> encode back to base64 WebM/Opus"
        if not self.groq_client:
            return {'error': 'Groq client not configured', 'status': 'error'}

        try:
            # Decode base64 WebM/Opus audio
            if not base64_audio or base64_audio.strip() == "":
                logger.warning("Empty base64 audio data received")
                return {'error': 'Empty base64 audio data', 'status': 'error'}

            logger.info(f"Processing audio chunk, base64 length: {len(base64_audio)}")
            audio_data = base64.b64decode(base64_audio)
            logger.info(f"Decoded audio data size: {len(audio_data)} bytes")
            
            if not audio_data or len(audio_data) == 0:
                logger.warning("Decoded audio data is empty")
                return {'error': 'Decoded audio data is empty', 'status': 'error'}

            # Convert WebM to WAV for better Whisper compatibility
            if AudioSegment is not None:
                try:
                    logger.info("Converting WebM audio to WAV for transcription...")
                    # Validate WebM data before conversion
                    webm_buffer = io.BytesIO(audio_data)
                    webm_segment = AudioSegment.from_file(webm_buffer, format="webm")
                    wav_buffer = io.BytesIO()
                    webm_segment.export(wav_buffer, format="wav")
                    wav_buffer.seek(0)
                    wav_buffer.name = "audio.wav"
                    audio_buffer = wav_buffer
                    logger.info("Audio conversion successful")
                except Exception as conv_error:
                    logger.warning(f'Audio conversion failed (possibly invalid WebM data): {conv_error}, using WebM directly')
                    audio_buffer = io.BytesIO(audio_data)
                    audio_buffer.name = "audio.webm"
            else:
                logger.warning('Audio processing libraries not available, using WebM directly')
                audio_buffer = io.BytesIO(audio_data)
                audio_buffer.name = "audio.webm"

            # Transcribe audio using Groq Whisper
            logger.info("Sending to Groq Whisper for transcription...")
            transcript = await self.transcribe_audio(audio_buffer)
            logger.info(f"Transcription result: '{transcript}'")

            if not transcript or transcript.strip() == "":
                return {
                    'transcript': '',
                    'ai_text': None,
                    'ai_audio_base64': None,
                    'status': 'no_speech'
                }

            # Generate AI response
            ai_response = await self.continue_interview(conversation_history or [], job_id)

            # Generate speech from AI response
            ai_audio_base64 = await self.text_to_speech_base64(ai_response)

            return {
                'transcript': transcript,
                'ai_text': ai_response,
                'ai_audio_base64': ai_audio_base64,
                'status': 'success'
            }

        except Exception as e:
            logger.error(f'Audio processing error: {e}')
            return {'error': str(e), 'status': 'error'}

    @functools.lru_cache(maxsize=1)
    def _get_face_detection(self):
        try:
            return mp.solutions.face_detection.FaceDetection(
                model_selection=0, min_detection_confidence=0.5
            )
        except Exception as e:
            logger.warning(f'MediaPipe face detection init failed: {e}. Disabling video analysis.')
            return None

    @functools.lru_cache(maxsize=1)
    def _get_pose(self):
        try:
            return mp.solutions.pose.Pose(
                min_detection_confidence=0.5, min_pose_confidence=0.5
            )
        except Exception as e:
            logger.warning(f'MediaPipe pose init failed: {e}. Disabling video analysis.')
            return None

    async def process_video_frame(self, base64_data: str, timestamp: int, job_id: str, conversation_history: Optional[List[Dict[str, str]]] = None, generate_ai: bool = True) -> Dict[str, Any]:
        "Process video chunk: MediaPipe face/posture -> visual analysis -> LLM next question."
        if not self.groq_client:
            return {'error': 'Groq client not configured', 'status': 'error'}
        
        if cv2 is None or np is None:
            return {'error': 'OpenCV or NumPy not installed', 'status': 'error'}

        # Decode base64 webp
        try:
            if ',' in base64_data:
                base64_data = base64_data.split(',')[1]
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
            face_detection = self._get_face_detection()
            face_desc = 'Face analysis unavailable'
            if face_detection:
                face_results = face_detection.process(rgb_frame)
                face_desc = 'Face detected' if face_results.detections else 'No face detected'

            # Pose estimation for posture
            pose = self._get_pose()
            posture_desc = 'Posture analysis unavailable'
            if pose:
                pose_results = pose.process(rgb_frame)
                posture_desc = 'Upright/confident posture' if pose_results.pose_landmarks else 'Posture not clear'

            # Visual 'STT' (no audio)
            visual_stt = f'No audio detected. Visual analysis: {face_desc}. {posture_desc}. Candidate appears engaged.'

            ai_text = None
            if generate_ai:
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
                'status': 'responding' if ai_text else 'analyzing',
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
