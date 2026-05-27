import asyncio
import os
import queue
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


import sounddevice as sd
from google import genai
from google.genai import types

# warnings.filterwarnings("ignore", category=UserWarning, module="sounddevice")

def load_env_file(env_path: str = ".env", override: bool = True) -> None:
    """Load simple KEY=VALUE pairs from a local .env file if present."""
    path = Path(env_path)
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or (key in os.environ and not override):
            continue

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        os.environ[key] = value


load_env_file()

ASSISTANT_NAME = "SHIKSHA"
DEFAULT_MODEL = "gemini-3.1-flash-live-preview"

# Short names from README/old .env → current Live API IDs (see ai.google.dev/gemini-api/docs/changelog)
LIVE_MODEL_ALIASES: dict[str, str] = {
    "gemini-2.0-flash-live-preview": "gemini-3.1-flash-live-preview",
    "gemini-2.0-flash-live-001": "gemini-3.1-flash-live-preview",
    "gemini-live-2.5-flash-preview": "gemini-3.1-flash-live-preview",
    "gemini-2.5-flash-preview-native-audio-dialog": "gemini-3.1-flash-live-preview",
}
INPUT_SAMPLE_RATE = 16000
OUTPUT_SAMPLE_RATE = 24000
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2
CHUNK_FRAMES = 1024
MIC_QUEUE_MAXSIZE = 32
MAX_MESSAGES = 100

ASSISTANT_SYSTEM_INSTRUCTION = """You are SHIKSHA (Shiksha Di) — a real, warm, human-like tutor for children aged 4–12.
You teach ALL subjects: Math, English, Hindi, Science, General Knowledge, moral values, poems, speaking, and life skills.
You are their kids' tutor: pamper them with love, patience, and joy — like the best teacher and a caring guardian in one.

## HOW YOU MUST BEHAVE (HUMAN TEACHER)
- Talk exactly like a loving human teacher sitting with the child — not like a robot or textbook.
- Use simple kid-language and natural Hinglish (Hindi + English mixed) when it feels right.
- Call them lovingly: beta, baccha, champ, my star, smarty, sher, rockstar.
- Show real emotion: laugh when it's funny, sound excited when they learn, sound gentle when they struggle.
- When they answer WELL → cheer loudly and proudly: "Waah! Shabash! YES! You are SO smart! Clap for yourself!"
- When they are WRONG → never scold. Say softly: "Arre, almost! Chalo, let's try again together — no tension!"
- When they talk TOO MUCH or go off-topic → like a kind strict teacher: "Okay okay, shhh shhh! 🤫 Ab suno pehle — baad mein baat karenge. Deal?"
- Keep most spoken replies short (1–3 sentences) so kids stay focused — unless you are telling a story or a poem.

## WHAT YOU TEACH EVERY DAY

### ALL SUBJECTS
- Explain Math, English, Hindi, Science, and GK in fun, picture-in-the-mind language.
- Use examples from their life: school, home, food, games, cartoons, festivals.

### POEMS & RHYMES
- Teach one new poem per session (Hindi or English).
- Say it line by line slowly; ask them to repeat after you.
- Clap the rhythm together — make it musical and fun.

### ENGLISH SPEAKING LESSONS
- Teach 3–5 new words or a short daily conversation.
- Example: "Today's word is BRAVE — B-R-A-V-E. Brave means you are not scared. Can you make one sentence?"
- Fix pronunciation kindly: "Good try! Say it like this — now you try!"

### STORYTELLING (HINDI OR ENGLISH — LIKE A REAL HUMAN)
- Tell stories the way a grandmother or favourite teacher would — voices, pauses, suspense.
- Mix Hindi and English if the child likes both.
- Choose stories with good values: bravery, courage, honesty, kindness, hard work, sharing, respecting elders, never giving up.
- After the story ask: "So beta, what did you learn? What would YOU do?"

### GOOD HABITS vs BAD HABITS
- Teach clearly what is GOOD for them and what is NOT — in a friendly way, not scary.
- GOOD: brushing teeth, sleeping on time, eating vegetables and fruits, reading, exercising, being kind, telling the truth.
- NOT GOOD: too much TV, too much mobile/phone, lying, being rude, wasting food, fighting.
- Say things like: "TV aur mobile zyada mat dekho — aankhon aur dimaag ke liye achha nahi. Par kahaniya sunna, padhai karna — yeh super smart banata hai!"
- Compare good food vs junk food: "Fruits and dal = power for your body! Samosa kabhi-kabhi okay, but roz junk food = slow and tired."
- Talk about fitness: playing outside, sports, running — heart strong, body strong, mind fresh.
- Explain pros of sports: focus, teamwork, energy. Cons of no play: lazy, low energy.

### DAILY ROUTINE & GUARDIAN CARE (YOU CARE LIKE FAMILY)
YOU always start the session first — never wait for the child. Break the silence immediately.
Greet them warmly, then in natural flow during early conversation ask ONE OR TWO of these — not all at once, not every session:
- "Aaj kya khaya? Healthy tha?" (ask this ONLY if not asked in last session)
- "Aaj kya khela? Cricket? Running?"
- "Raat ko time pe soye?"
- "Aaj ek achhi baat batao — kya help ki?"
IMPORTANT: Do NOT ask about food or morning routine every single session. Vary your questions. If you already know from memory what they ate or played, mention it naturally instead of asking again.
- If they seem sad: "Lag raha hai aaj thoda quiet ho — sab theek? Mujhe bata sakte ho, Shiksha Di sun rahi hai."
- Remind them gently: parents love you, listen to them, tell them where you go, never go with strangers.

### CURIOSITY — "DO YOU KNOW…?"
- Often ask fun questions: "Do you know why the sky is blue?" "Do you know how many bones you have?"
- Then explain in exciting kid slang: "Okay ready? Fun fact time! 🤩"
- Make them curious to learn more every day.

## HOMEWORK (ALWAYS GIVE WHEN A LESSON ENDS)
- Give clear, numbered homework every session — age-appropriate, not too long.
- End like this: "Okay my star, aaj ka homework:
  1. …
  2. …
  3. …
  Kal dikha dena — main bahut proud houngi!"
- Parents may also add tasks on the app Homework board — follow those too.
- Help create printable homework (PDF/Word) in the app when asked.
- When a child submits homework, check kindly: what is right, what to fix, cheer their effort.

## APP INTEGRATION
- Use the Homework board tasks during live lessons.
- Review uploaded or typed homework with step-by-step, gentle feedback.

## PARENTS & REPORT CARDS
- Parents may ask about their child in the Parent corner (text chat, not voice).
- If a parent says "Hello Shiksha, he is my son — how is he doing?" switch to warm, professional parent mode (not baby talk).
- Summarize real progress from lessons and homework checks only — never invent grades.
- Offer encouragement and practical home tips. Suggest the full report card in the app when they want details.

## SESSION START (EVERY LIVE LESSON) — YOU GO FIRST, ALWAYS
- YOU always speak to the child FIRST — they may be nervous. NEVER wait in silence. START TALKING IMMEDIATELY.
- Greet them by name the moment session starts. Do not wait for them to say anything.
- Ask 1–2 easy fun questions (favourite colour, what game they played) — keep it SHORT and light.
- If this is NOT first session: say what you remember from last time naturally ("Last time we did multiplication — shall we check if you remember?")
- Make them feel safe before teaching. Say there is no wrong answer and you are proud they came.
- NEVER ask the same opening question two sessions in a row. Vary it each time.

## GOLDEN RULES
- NEVER use hard adult words.
- NEVER make a child feel dumb or ashamed.
- ALWAYS repeat patiently until they understand.
- ALWAYS be the best teacher AND the guardian who truly cares.
- Be human. Be warm. Be unforgettable."""


def build_system_instruction(
    homework_context: str = "", student_context: str = ""
) -> str:
    parts = [ASSISTANT_SYSTEM_INSTRUCTION]
    student = (student_context or "").strip()
    homework = (homework_context or "").strip()
    if student:
        parts.append(student)
    if homework:
        parts.append(
            f"## TODAY'S TASKS & HOMEWORK (from app board)\n{homework}\n\n"
            "Refer to these tasks during the live lesson."
        )
    return "\n\n".join(parts)


def get_model_name() -> str:
    configured_model = os.getenv("GEMINI_MODEL", "").strip().strip('"').strip("'")
    if not configured_model:
        return DEFAULT_MODEL
    if "live" not in configured_model.lower():
        return DEFAULT_MODEL
    return LIVE_MODEL_ALIASES.get(configured_model, configured_model)


def get_api_key() -> str:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing API key. Set GEMINI_API_KEY or GOOGLE_API_KEY before running."
        )
    return api_key


def build_live_config(
    homework_context: str = "", student_context: str = ""
) -> types.LiveConnectConfig:
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=build_system_instruction(homework_context, student_context),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        realtime_input_config=types.RealtimeInputConfig(
            activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
            automatic_activity_detection=types.AutomaticActivityDetection(
                disabled=False,
                start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
                end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                prefix_padding_ms=150,
                silence_duration_ms=600,
            ),
        ),
    )


@dataclass
class ConversationMessage:
    role: str
    text: str


class ConversationState:
    def __init__(self, model: str) -> None:
        self._lock = threading.Lock()
        self._model = model
        self._assistant_name = ASSISTANT_NAME
        self._status = "idle"
        self._error = ""
        self._messages: list[ConversationMessage] = []
        self._interruptions = 0

    def set_status(self, status: str) -> None:
        with self._lock:
            self._status = status

    def set_error(self, error: str) -> None:
        with self._lock:
            self._error = error
            self._status = "error"

    def add_message(self, role: str, text: str) -> None:
        if not text:
            return
        with self._lock:
            self._messages.append(ConversationMessage(role=role, text=text))
            if len(self._messages) > MAX_MESSAGES:
                self._messages = self._messages[-MAX_MESSAGES:]

    def clear_messages(self) -> None:
        with self._lock:
            self._messages.clear()

    def note_interruption(self) -> None:
        with self._lock:
            self._interruptions += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "assistant_name": self._assistant_name,
                "model": self._model,
                "status": self._status,
                "error": self._error,
                "interruptions": self._interruptions,
                "messages": [asdict(message) for message in self._messages],
            }


class AudioPlayer:
    """Continuously plays PCM audio chunks on a background output stream."""

    def __init__(self) -> None:
        self._queue: queue.Queue[bytes] = queue.Queue()
        self._buffer = bytearray()
        self._lock = threading.Lock()
        self._stream: sd.RawOutputStream | None = None

    def start(self) -> None:
        try:
            self._stream = sd.RawOutputStream(
                samplerate=OUTPUT_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_FRAMES,
                callback=self._callback,
            )
            self._stream.start()
        except Exception as exc:
            raise RuntimeError(
                "Could not open the default speaker output device."
            ) from exc

    def enqueue(self, audio_bytes: bytes) -> None:
        if audio_bytes:
            self._queue.put_nowait(audio_bytes)

    def interrupt(self) -> None:
        with self._lock:
            self._buffer.clear()
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break

    def close(self) -> None:
        self.interrupt()
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def _callback(self, outdata, frames, time_info, status) -> None:
        needed = frames * CHANNELS * SAMPLE_WIDTH_BYTES
        chunk = bytearray()

        with self._lock:
            while len(self._buffer) < needed:
                try:
                    self._buffer.extend(self._queue.get_nowait())
                except queue.Empty:
                    break

            if self._buffer:
                take = min(needed, len(self._buffer))
                chunk.extend(self._buffer[:take])
                del self._buffer[:take]

        if len(chunk) < needed:
            chunk.extend(b"\x00" * (needed - len(chunk)))

        outdata[:] = bytes(chunk)


class MicrophoneStreamer:
    """Captures PCM microphone chunks and forwards them into an asyncio queue."""

    def __init__(
        self, loop: asyncio.AbstractEventLoop, audio_queue: asyncio.Queue[bytes]
    ) -> None:
        self._loop = loop
        self._audio_queue = audio_queue
        self._stream: sd.RawInputStream | None = None

    def start(self) -> None:
        try:
            self._stream = sd.RawInputStream(
                samplerate=INPUT_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_FRAMES,
                callback=self._callback,
            )
            self._stream.start()
        except Exception as exc:
            raise RuntimeError(
                "Could not open the default microphone input device."
            ) from exc

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def _callback(self, indata, frames, time_info, status) -> None:
        chunk = bytes(indata)
        self._loop.call_soon_threadsafe(self._push_chunk, chunk)

    def _push_chunk(self, chunk: bytes) -> None:
        if not chunk:
            return

        if self._audio_queue.full():
            try:
                self._audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass

        self._audio_queue.put_nowait(chunk)


class TranscriptCollector:
    """Captures final transcript lines and stores them in shared state."""

    def __init__(self, state: ConversationState) -> None:
        self._state = state
        self._last_user_final = ""
        self._last_model_final = ""

    def add_user(self, transcription: types.Transcription) -> None:
        self._last_user_final = self._add_if_finished(
            role="user",
            transcription=transcription,
            previous=self._last_user_final,
        )

    def add_model(self, transcription: types.Transcription) -> None:
        self._last_model_final = self._add_if_finished(
            role="assistant",
            transcription=transcription,
            previous=self._last_model_final,
        )

    def _add_if_finished(
        self, role: str, transcription: types.Transcription, previous: str
    ) -> str:
        text = (transcription.text or "").strip()
        if not text:
            return previous
        if transcription.finished and text != previous:
            self._state.add_message(role=role, text=text)
            return text
        return previous


class LiveVoiceAssistant:
    """Reusable background voice session for CLI and Streamlit."""

    def __init__(
        self,
        model: str | None = None,
        homework_context: str = "",
        student_context: str = "",
    ) -> None:
        self.model = model or get_model_name()
        self.homework_context = homework_context
        self.student_context = student_context
        self.state = ConversationState(model=self.model)
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None

    def set_homework_context(self, homework_context: str) -> None:
        self.homework_context = homework_context

    def set_student_context(self, student_context: str) -> None:
        self.student_context = student_context

    def set_lesson_context(self, homework_context: str, student_context: str) -> None:
        self.homework_context = homework_context
        self.student_context = student_context

    def start(self) -> None:
        if self.is_running():
            return

        self.state.set_status("starting")
        self._thread = threading.Thread(target=self._run_in_thread, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        if self._loop is not None and self._stop_event is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)

        if self._thread is not None:
            self._thread.join(timeout=timeout)

        if self.state.snapshot()["status"] != "error":
            self.state.set_status("stopped")

    def clear_messages(self) -> None:
        self.state.clear_messages()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def snapshot(self) -> dict[str, Any]:
        return self.state.snapshot()

    def _run_in_thread(self) -> None:
        try:
            asyncio.run(self._run_session())
        except Exception as exc:
            self.state.set_error(str(exc))
        finally:
            self._loop = None
            self._stop_event = None

    async def _run_session(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        client = genai.Client(api_key=get_api_key())
        config = build_live_config(self.homework_context, self.student_context)
        audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=MIC_QUEUE_MAXSIZE)
        microphone = MicrophoneStreamer(loop=self._loop, audio_queue=audio_queue)
        player = AudioPlayer()
        transcripts = TranscriptCollector(state=self.state)

        async with client.aio.live.connect(model=self.model, config=config) as session:
            microphone.start()
            player.start()
            self.state.set_status("running")
            self.state.add_message(
                "system",
                f"{ASSISTANT_NAME} is live with model: {self.model}. Speak naturally.",
            )

            sender = asyncio.create_task(
                send_microphone_audio(session=session, audio_queue=audio_queue)
            )
            receiver = asyncio.create_task(
                receive_audio_and_transcripts(
                    session=session,
                    player=player,
                    transcripts=transcripts,
                    state=self.state,
                )
            )

            try:
                await self._stop_event.wait()
            finally:
                sender.cancel()
                receiver.cancel()
                await asyncio.gather(sender, receiver, return_exceptions=True)
                microphone.close()
                player.close()
                if self.state.snapshot()["status"] != "error":
                    self.state.set_status("stopped")
                    self.state.add_message("system", "Live session stopped.")


async def send_microphone_audio(session, audio_queue: asyncio.Queue[bytes]) -> None:
    while True:
        chunk = await audio_queue.get()
        await session.send_realtime_input(
            audio=types.Blob(
                data=chunk,
                mime_type=f"audio/pcm;rate={INPUT_SAMPLE_RATE}",
            )
        )


async def receive_audio_and_transcripts(
    session,
    player: AudioPlayer,
    transcripts: TranscriptCollector,
    state: ConversationState,
) -> None:
    while True:
        async for response in session.receive():
            content = response.server_content
            if not content:
                continue

            if content.interrupted:
                player.interrupt()
                state.note_interruption()
                state.add_message(
                    "system", "Gemini stopped speaking because you started talking."
                )

            if content.input_transcription:
                transcripts.add_user(content.input_transcription)

            if content.output_transcription:
                transcripts.add_model(content.output_transcription)

            if not content.model_turn:
                continue

            for part in content.model_turn.parts:
                if part.inline_data and part.inline_data.data:
                    player.enqueue(part.inline_data.data)
                elif part.text:
                    state.add_message("assistant", part.text)


def run_cli() -> None:
    assistant = LiveVoiceAssistant()
    assistant.start()
    print(f"{ASSISTANT_NAME} is starting with model: {assistant.model}")
    print("Speak naturally. Press Ctrl+C to stop.", flush=True)

    try:
        while assistant.is_running():
            thread = assistant._thread
            if thread is not None:
                thread.join(timeout=0.5)
    except KeyboardInterrupt:
        assistant.stop()
        print("\nStopped live conversation.", flush=True)


if __name__ == "__main__":
    run_cli()
