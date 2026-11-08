import base64
import unittest
from unittest.mock import MagicMock, patch

from app.services.interview import AudioPayloadError, InterviewService


class InterviewAudioPreparationTests(unittest.TestCase):
    def setUp(self):
        self.service = InterviewService.__new__(InterviewService)

    def _encoded(self, data: bytes) -> str:
        return base64.b64encode(data).decode("ascii")

    def test_rejects_empty_payload(self):
        with self.assertRaises(AudioPayloadError) as raised:
            self.service._prepare_audio_for_transcription("  ")
        self.assertEqual(raised.exception.category, "format")

    def test_rejects_malformed_base64(self):
        with self.assertRaises(AudioPayloadError) as raised:
            self.service._prepare_audio_for_transcription("%%%not-base64%%")
        self.assertEqual(raised.exception.category, "decode")

    def test_rejects_unknown_audio_container(self):
        with self.assertRaises(AudioPayloadError) as raised:
            self.service._prepare_audio_for_transcription(self._encoded(b"not audio"))
        self.assertEqual(raised.exception.category, "format")

    def test_rejects_mime_type_that_does_not_match_payload(self):
        payload = "data:audio/wav;base64," + self._encoded(b"ID3" + bytes(20))
        with self.assertRaises(AudioPayloadError) as raised:
            self.service._prepare_audio_for_transcription(payload)
        self.assertEqual(raised.exception.category, "format")

    def test_supported_formats_are_normalized_to_wav(self):
        cases = (
            (b"\x1a\x45\xdf\xa3" + bytes(20), "webm"),
            (b"RIFF" + bytes(4) + b"WAVE" + bytes(20), "wav"),
            (b"ID3" + bytes(20), "mp3"),
        )
        segment = MagicMock()
        segment.__len__ = MagicMock(return_value=1000)
        segment.dBFS = -20.0
        segment.set_channels.return_value = segment
        segment.set_frame_rate.return_value = segment
        segment.set_sample_width.return_value = segment

        def export(output, format):
            self.assertEqual(format, "wav")
            output.write(b"normalized wav")

        segment.export.side_effect = export
        with patch("app.services.interview.AudioSegment") as audio_segment:
            audio_segment.from_file.return_value = segment
            for payload, expected_format in cases:
                with self.subTest(format=expected_format):
                    result = self.service._prepare_audio_for_transcription(self._encoded(payload))
                    self.assertEqual(result.name, "audio.wav")
                    self.assertEqual(result.read(), b"normalized wav")
                    self.assertEqual(audio_segment.from_file.call_args.kwargs["format"], expected_format)
        segment.set_channels.assert_called_with(1)
        segment.set_frame_rate.assert_called_with(16000)
        segment.set_sample_width.assert_called_with(2)

    def test_silence_is_flagged_as_no_speech(self):
        silence_segment = MagicMock()
        silence_segment.__len__ = MagicMock(return_value=1000)
        silence_segment.dBFS = float("-inf")
        with patch("app.services.interview.AudioSegment") as audio_segment:
            audio_segment.from_file.return_value = silence_segment
            result = self.service._prepare_audio_for_transcription(
                self._encoded(b"RIFF" + bytes(4) + b"WAVE" + bytes(20))
            )
        self.assertTrue(result.no_speech)

    def test_data_url_normalization_and_transcription_no_speech_response(self):
        silence_segment = MagicMock()
        silence_segment.__len__ = MagicMock(return_value=1000)
        silence_segment.dBFS = -60.0
        service = InterviewService.__new__(InterviewService)
        service.groq_client = object()
        with patch("app.services.interview.AudioSegment") as audio_segment:
            audio_segment.from_file.return_value = silence_segment
            result = self._run(service, "data:audio/wav;base64," + self._encoded(
                b"RIFF" + bytes(4) + b"WAVE" + bytes(20)
            ))
        self.assertEqual(result["status"], "no_speech")
        self.assertEqual(result["transcript"], "")

    @staticmethod
    def _run(service, payload):
        import asyncio
        return asyncio.run(service.handle_audio_turn(payload, "job-id"))


if __name__ == "__main__":
    unittest.main()
