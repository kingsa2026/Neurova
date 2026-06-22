"""
SAPI5 TTS - Windows Speech API TTS engine
Uses Windows SAPI5 via comtypes for offline speech synthesis.
"""

import io
import struct
import tempfile
import threading
import typing
import wave

from neurova.tts.base import TTSBase


class SAPI5TTS(TTSBase):
    """
    Windows SAPI5 TTS engine.

    Uses the built-in Windows Speech API for speech synthesis.
    Works offline without any external dependencies beyond comtypes.
    """

    def __init__(self, voice_name: str = None, rate=None, volume=None):
        super().__init__()
        self._voice_name = voice_name
        # Parse rate: "+0%" -> 0, "-50%" -> -5, "+100%" -> 10
        if isinstance(rate, str):
            rate = rate.strip().replace('%', '').replace('+', '')
            try:
                self._rate = int(int(rate) / 10)
            except ValueError:
                self._rate = 0
        else:
            self._rate = rate or 0
        # Parse volume: "+0%" -> 100, "50" -> 50
        if isinstance(volume, str):
            volume = volume.strip().replace('%', '').replace('+', '')
            try:
                self._volume = int(volume)
            except ValueError:
                self._volume = 100
        else:
            self._volume = volume or 100
        self._engine = None

    async def initialize(self) -> bool:
        try:
            import comtypes.client

            self._engine = comtypes.client.CreateObject("SAPI.SpVoice")
            self._engine.Rate = self._rate
            self._engine.Volume = self._volume

            if self._voice_name:
                for voice in self._engine.GetVoices():
                    if self._voice_name.lower() in voice.GetDescription().lower():
                        self._engine.Voice = voice
                        break

            self._initialized = True
            self._logger.info(
                "SAPI5 TTS initialized: voice=%s, rate=%d",
                self._engine.Voice.GetDescription(),
                self._rate,
            )
            return True
        except Exception as e:
            self._logger.error("SAPI5 TTS init failed: %s", e)
            return False

    async def synthesize(self, text: str, **kwargs) -> bytes:
        if not self.validate_text(text):
            return b""
        if not self._engine:
            return b""

        try:
            return await self._synthesize_to_wav(text)
        except Exception as e:
            self._logger.error("SAPI5 synthesize failed: %s", e)
            return b""

    async def _synthesize_to_wav(self, text: str) -> bytes:
        import comtypes.client

        stream = comtypes.client.CreateObject("SAPI.SpFileStream")
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()

        try:
            stream.Open(tmp.name, 3, False)
            self._engine.AudioOutputStream = stream
            self._engine.Speak(text, 0)
            stream.Close()

            with open(tmp.name, "rb") as f:
                return f.read()
        finally:
            try:
                import os
                os.unlink(tmp.name)
            except OSError:
                pass

    async def synthesize_stream(self, text: str) -> typing.AsyncGenerator[bytes, None]:
        wav_data = await self.synthesize(text)
        if wav_data:
            yield wav_data

    async def shutdown(self) -> None:
        self._engine = None
        self._initialized = False
        self._logger.info("SAPI5 TTS shut down")
