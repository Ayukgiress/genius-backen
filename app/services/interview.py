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


class AudioPayloadError(ValueError):
    """An audio input failure safe to return to the client."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


class VideoPayloadError(ValueError):
    """A video frame input failure safe to return to the client."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


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
            
            if not audio_bytes or len(audio_bytes) < 50:
                logger.warning(f"Audio too small to transcribe: {len(audio_bytes) if audio_bytes else 0} bytes")
                return ""

            logger.info(f"Sending {len(audio_bytes)} bytes to Groq Whisper for transcription...")
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
            logger.exception("Speech recognition provider failed [transcription]")
            raise

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
                try:
                    engine = pyttsx3.init()
                except (RuntimeError, Exception) as init_err:
                    logger.error(f"Failed to initialize pyttsx3 (missing espeak?): {init_err}")
                    return None

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
                logger.warning("pyttsx3 generated empty audio or failed to initialize")
                return None
        except Exception as e:
            logger.error(f'pyttsx3 TTS error: {e}')
            return None

    async def text_to_speech_base64(self, text: str) -> Optional[str]:
        """Convert text to speech and return as base64 encoded string."""
        try:
            # Generate speech from AI response
            speech_bytes = await self.generate_speech(text)
            
            if not speech_bytes:
                logger.warning("No speech bytes generated, skipping audio encoding")
                return None

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

    @staticmethod
    def package_response(
        *,
        content: Optional[str] = None,
        transcript: Optional[str] = None,
        ai_audio_data: Optional[str] = None,
        visual_data: Optional[Dict[str, Any]] = None,
        status: str = "success",
        error: Optional[str] = None,
        **metadata: Any,
    ) -> Dict[str, Any]:
        """Return the canonical media response and transitional legacy aliases."""
        result = {
            "content": content,
            "transcript": transcript,
            "ai_audio_data": ai_audio_data,
            "audio_data": ai_audio_data,
            "visual_data": visual_data,
            "status": status,
            "response_status": status,
            "error": error,
            "response_mode": None,
            "ai_avatar_video_url": None,
            "avatar_type": None,
            "avatar_style": None,
            "persona": None,
            "video_status": None,
            "playback_metadata": None,
            # Compatibility aliases for existing clients.
            "ai_text": content,
            "ai_audio_base64": ai_audio_data,
        }
        result.update(metadata)
        return result

    def _prepare_audio_for_transcription(self, base64_audio: str) -> io.BytesIO:
        """Validate and convert supported base64 audio into canonical mono 16 kHz WAV."""
        if not isinstance(base64_audio, str) or not base64_audio.strip():
            logger.warning("Audio input rejected [format]: empty payload")
            raise AudioPayloadError("format", "Audio payload is empty.")

        encoded_audio = base64_audio.strip()
        declared_type = None
        if encoded_audio.startswith("data:"):
            header, separator, encoded_audio = encoded_audio.partition(",")
            if not separator or ";base64" not in header.lower():
                logger.warning("Audio input rejected [decode]: invalid data URL")
                raise AudioPayloadError("decode", "Audio data URL must contain valid base64 data.")
            declared_type = header[5:].split(";", 1)[0].lower()
            supported_types = {
                "audio/webm": "webm",
                "audio/wav": "wav",
                "audio/x-wav": "wav",
                "audio/mpeg": "mp3",
                "audio/mp3": "mp3",
            }
            if declared_type not in supported_types:
                logger.warning("Audio input rejected [format]: unsupported MIME type %s", declared_type)
                raise AudioPayloadError("format", "Unsupported audio format. Use WebM, WAV, or MP3.")
            declared_format = supported_types[declared_type]
        else:
            declared_format = None

        # Permit ordinary whitespace in chunked base64, but reject every other
        # non-alphabet character by decoding with validate=True.
        encoded_audio = "".join(encoded_audio.split())
        if not encoded_audio:
            logger.warning("Audio input rejected [format]: empty base64 data")
            raise AudioPayloadError("format", "Audio payload is empty.")
        if len(encoded_audio) > 4 * ((25 * 1024 * 1024 + 2) // 3):
            logger.warning("Audio input rejected [decode]: payload exceeds 25 MiB limit")
            raise AudioPayloadError("decode", "Audio payload exceeds the 25 MiB limit.")
        try:
            audio_data = base64.b64decode(encoded_audio, validate=True)
        except (ValueError, TypeError) as decode_error:
            logger.warning("Audio input rejected [decode]: malformed base64 (%s)", decode_error)
            raise AudioPayloadError("decode", "Audio payload is not valid base64.") from decode_error
        if not audio_data:
            logger.warning("Audio input rejected [format]: decoded payload is empty")
            raise AudioPayloadError("format", "Audio payload is empty.")
        if len(audio_data) > 25 * 1024 * 1024:
            logger.warning("Audio input rejected [decode]: decoded payload exceeds 25 MiB limit")
            raise AudioPayloadError("decode", "Audio payload exceeds the 25 MiB limit.")

        if audio_data.startswith(b"\x1a\x45\xdf\xa3"):
            detected_format = "webm"
        elif len(audio_data) >= 12 and audio_data[:4] == b"RIFF" and audio_data[8:12] == b"WAVE":
            detected_format = "wav"
        elif audio_data.startswith(b"ID3") or (
            len(audio_data) >= 2 and audio_data[0] == 0xFF and (audio_data[1] & 0xE0) == 0xE0
        ):
            detected_format = "mp3"
        else:
            logger.warning("Audio input rejected [format]: unrecognized audio container")
            raise AudioPayloadError("format", "Audio format could not be identified. Use WebM, WAV, or MP3.")

        if declared_format and declared_format != detected_format:
            logger.warning(
                "Audio input rejected [format]: MIME type %s does not match %s data",
                declared_type,
                detected_format,
            )
            raise AudioPayloadError("format", "Declared audio format does not match the payload.")
        if AudioSegment is None:
            logger.error("Audio normalization unavailable [format]: pydub is not installed")
            raise AudioPayloadError("format", "Audio processing is temporarily unavailable.")

        try:
            segment = AudioSegment.from_file(io.BytesIO(audio_data), format=detected_format)
        except Exception as conversion_error:
            logger.warning("Audio normalization failed [format] for %s: %s", detected_format, conversion_error)
            raise AudioPayloadError("format", "Audio file is malformed or cannot be decoded.") from conversion_error

        # Very short and effectively silent chunks are normal microphone/VAD
        # outcomes, not provider failures. Check before any gain normalization.
        if len(segment) < 250 or segment.dBFS == float("-inf") or segment.dBFS <= -55:
            logger.info(
                "Audio classified as no_speech: duration_ms=%s level_dbfs=%s",
                len(segment),
                segment.dBFS,
            )
            empty_wav = io.BytesIO()
            empty_wav.name = "audio.wav"
            empty_wav.no_speech = True
            return empty_wav

        normalized = segment.set_channels(1).set_frame_rate(16000).set_sample_width(2)
        wav_buffer = io.BytesIO()
        try:
            normalized.export(wav_buffer, format="wav")
        except Exception as conversion_error:
            logger.exception("Audio normalization failed [format] while exporting WAV")
            raise AudioPayloadError("format", "Audio could not be normalized for transcription.") from conversion_error
        wav_buffer.seek(0)
        wav_buffer.name = "audio.wav"
        wav_buffer.no_speech = False
        logger.info(
            "Audio normalized: source_format=%s duration_ms=%s channels=1 sample_rate=16000",
            detected_format,
            len(normalized),
        )
        return wav_buffer

    @staticmethod
    def _decode_video_frame_payload(base64_data: str) -> bytes:
        """Strictly decode a bounded image payload or raise a safe input error."""
        if not isinstance(base64_data, str) or not base64_data.strip():
            raise VideoPayloadError("format", "Video frame payload is empty.")
        encoded_image = base64_data.strip()
        if encoded_image.startswith("data:"):
            header, separator, encoded_image = encoded_image.partition(",")
            if (
                not separator
                or ";base64" not in header.lower()
                or header[5:].split(";", 1)[0].lower()
                not in {"image/jpeg", "image/png", "image/webp"}
            ):
                raise VideoPayloadError("format", "Video frame data URL is invalid.")
        encoded_image = "".join(encoded_image.split())
        if not encoded_image or len(encoded_image) > 8_000_000:
            raise VideoPayloadError("format", "Video frame exceeds the supported size limit.")
        try:
            image_data = base64.b64decode(encoded_image, validate=True)
        except (ValueError, TypeError) as error:
            raise VideoPayloadError("decode", "Video frame is not valid base64.") from error
        if not image_data or len(image_data) > 6 * 1024 * 1024:
            raise VideoPayloadError("format", "Video frame exceeds the supported size limit.")
        return image_data

    async def handle_audio_turn(
        self,
        base64_audio: str,
        job_id: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Orchestrate one audio turn for HTTP and WebSocket callers alike."""
        if not self.groq_client:
            return self.package_response(status="error", error="Groq client not configured")

        try:
            logger.info(
                "Processing interview audio: job_id=%s encoded_length=%s",
                job_id,
                len(base64_audio) if isinstance(base64_audio, str) else 0,
            )
            audio_buffer = self._prepare_audio_for_transcription(base64_audio)
        except AudioPayloadError as error:
            logger.warning("Interview audio rejected: job_id=%s category=%s", job_id, error.category)
            return self.package_response(status="error", error=str(error), error_type=error.category)

        if getattr(audio_buffer, "no_speech", False):
            return self.package_response(status="no_speech", transcript="")
        if not self.groq_client:
            return self.package_response(status="error", error="Speech recognition is not configured.", error_type="transcription")

        try:
            logger.info("Transcribing normalized audio [transcription]")
            transcript = await self.transcribe_audio(audio_buffer)
        except Exception as error:
            logger.exception("Audio transcription failed: job_id=%s", job_id)
            return self.package_response(
                status="error",
                error="Audio transcription failed. Please try recording again.",
                error_type="transcription",
            )
        logger.info("Transcription complete: characters=%s", len(transcript or ""))
        if not transcript or not transcript.strip():
            logger.info("Transcription classified as no_speech")
            return self.package_response(status="no_speech", transcript="")

        try:
            logger.info("Generating interview response: job_id=%s", job_id)
            response_history = list(conversation_history or [])
            response_history.append({"role": "user", "content": transcript})
            ai_response = await self.continue_interview(response_history, job_id)
            if not ai_response or not ai_response.strip():
                logger.warning("AI generation returned empty content [ai_generation]; using fallback")
                ai_response = "I see. Could you please tell me more about that, or should we move on to the next question?"
        except Exception:
            logger.exception("Interview response generation failed: job_id=%s", job_id)
            return self.package_response(
                status="error",
                error="Could not generate an interview response. Please try again.",
                error_type="ai_generation",
            )

        # Speech is optional: TTS provider failures degrade to text-only.
        ai_audio_base64 = await self.text_to_speech_base64(ai_response)
        return self.package_response(
            content=ai_response,
            transcript=transcript,
            ai_audio_data=ai_audio_base64,
            status="success",
            response_mode="text_audio" if ai_audio_base64 else "text",
            ai_avatar_video_url=None,
            avatar_type=None,
            avatar_style=None,
            persona=None,
            video_status=None,
            playback_metadata=None,
        )

    async def process_audio_chunk(
        self,
        base64_audio: str,
        job_id: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Backward-compatible alias for the shared audio turn handler."""
        return await self.handle_audio_turn(base64_audio, job_id, conversation_history)

    async def generate_text_turn(
        self,
        conversation_history: List[Dict[str, str]],
        job_id: str,
        *,
        generate_audio: bool = False,
    ) -> Dict[str, Any]:
        """Generate and package a text turn, optionally synthesizing speech."""
        try:
            logger.info("Generating text interview response: job_id=%s history_messages=%s", job_id, len(conversation_history))
            content = await self.continue_interview(conversation_history, job_id)
            if not content or not content.strip():
                raise ValueError("AI generated an empty response")
            audio_data = (
                await self.text_to_speech_base64(content)
                if generate_audio
                else None
            )
            return self.package_response(
                content=content,
                ai_audio_data=audio_data,
                status="success",
                response_mode="text_audio" if audio_data else "text",
            )
        except Exception as error:
            logger.exception("Text interview turn failed: job_id=%s", job_id)
            return self.package_response(
                status="error",
                error="Could not generate an interview response. Please try again.",
                error_type="ai_generation",
            )

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
            return self.package_response(status="error", error="Groq client not configured")
        
        if cv2 is None or np is None:
            return self.package_response(status="error", error="OpenCV or NumPy not installed")

        # Decode only bounded image payloads; do not silently ignore malformed
        # characters or accept arbitrary data URLs from the WebSocket client.
        try:
            image_data = self._decode_video_frame_payload(base64_data)
            nparr = np.frombuffer(image_data, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame is None:
                return self.package_response(
                    status="error",
                    error="Video frame could not be decoded.",
                    error_type="decode",
                )
            if frame.shape[0] * frame.shape[1] > 16_000_000:
                return self.package_response(
                    status="error",
                    error="Video frame dimensions exceed the supported limit.",
                    error_type="format",
                )
        except VideoPayloadError as error:
            logger.info("Video frame rejected: %s", error)
            return self.package_response(
                status="error",
                error=str(error),
                error_type=error.category,
            )
        except Exception:
            logger.exception("Video frame decoding failed")
            return self.package_response(
                status="error",
                error="Video frame could not be decoded.",
                error_type="decode",
            )

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

            visual_data = {"face": face_desc, "posture": posture_desc}
            response_status = "responding" if ai_text else "analyzing"
            return self.package_response(
                content=ai_text,
                transcript=visual_stt,
                visual_data=visual_data,
                status=response_status,
                response_mode="text" if ai_text else "visual_analysis",
                ai_audio_data=None,
                ai_avatar_video_url=None,
                avatar_type=None,
                avatar_style=None,
                persona=None,
                video_status=None,
                playback_metadata=None,
                timestamp=timestamp,
                # Legacy key retained for existing video clients.
                visual=visual_data,
            )

        except Exception as error:
            logger.exception("Video/person analysis failed")
            return self.package_response(status="error", error=str(error))
        finally:
            # Privacy: delete frame data
            if 'frame' in locals():
                del frame
            if 'nparr' in locals():
                del nparr
            if rgb_frame is not None:
                del rgb_frame

    async def analyze_video_person(
        self,
        base64_data: str,
        timestamp: int,
        job_id: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        generate_ai: bool = True,
    ) -> Dict[str, Any]:
        """Domain-named entry point for video/person analysis orchestration."""
        return await self.process_video_frame(
            base64_data,
            timestamp,
            job_id,
            conversation_history,
            generate_ai,
        )

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
                {'role': 'user', 'content': 'Please start the interview by introducing yourself and asking the first question.'}
            ],
            temperature=0.7,
            max_tokens=1000
        )

        initial_message = response.choices[0].message.content
        
        # Generate audio for initial message
        initial_audio_base64 = await self.text_to_speech_base64(initial_message)

        packaged = self.package_response(
            content=initial_message,
            transcript=None,
            ai_audio_data=initial_audio_base64,
            status="success",
            response_mode="text_audio" if initial_audio_base64 else "text",
            ai_avatar_video_url=None,
            avatar_type=None,
            avatar_style=None,
            persona=None,
            video_status=None,
            playback_metadata=None,
        )
        packaged.update({
            'initial_message': initial_message,
            'initial_audio_base64': initial_audio_base64,
            'job_title': job_dict.get('title', 'Unknown Position'),
            'company': job_dict.get('company', 'Unknown Company')
        })
        return packaged

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
