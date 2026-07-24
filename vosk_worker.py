import asyncio
import json
import os
import queue
import sys

from discord_bot import DiscordBot

import sounddevice as sd
from vosk import KaldiRecognizer, Model

# Reading the data in the config.json file.
with open("config.json", "r") as file:
    config = json.load(file)

MY_USER_ID = config["MY_USER_ID"] 
MY_SERVER_ID = config["MY_SERVER_ID"] 
WAKE_WORD = config["WAKE_WORD"] 
VOSK_MODEL_PATH = config["VOSK_MODEL_PATH"] 
SAMPLE_RATE = config["SAMPLE_RATE"] 

# Table to convert word numbers to integers.
word_to_int = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7
}

# Checks if a Vosk model is in the directory of the script.
if not os.path.exists(VOSK_MODEL_PATH):
    print("[Vosk] You do not have a vosk model installed. ")
    sys.exit(1)

class VoskWorker:
    def __init__(self, shutdown_event: asyncio.Event, discord_bot: "DiscordBot") -> None:
        self.shutdown_event = shutdown_event
        self.discord_bot = discord_bot
        self.mic_queue: queue.Queue[bytes] = queue.Queue()
        self.is_awake = False
        self.model = Model(VOSK_MODEL_PATH)
        self.recognizer = KaldiRecognizer(self.model, SAMPLE_RATE)

    # Processes the text generated from Vosk and carrys out a function
    async def process_command(self, text: str) -> bool:
        words = text.lower().split()

        if not words:
            return False

        command_word = words[0]
        target_word = words[1] if len(words) > 1 else ""

        print(f"[Vosk] Parsed command=\"{command_word}\", target=\"{target_word}\"")

        if command_word in {"stop", "quit"}:
            return True
        
        if not target_word or target_word not in word_to_int:
            print(f"[Vosk] Invalid or missing target: \"{target_word}\"")
            return False

        target_list = await self.discord_bot.list_users_in_vc()
        target_index = word_to_int[target_word]

        if target_index >= len(target_list):
            print(f"[Vosk] Target index {target_index} out of bounds for current VC list.")
            return False
        
        target_id = target_list[target_index]

        if "kick" in command_word:
            await self.discord_bot.vc_kick(MY_SERVER_ID, target_id)

        elif command_word == "deafen":
            await self.discord_bot.vc_deafen(MY_SERVER_ID, target_id)

        elif command_word == "mute":
            await self.discord_bot.vc_mute(MY_SERVER_ID, target_id)

        else:
            print("[Vosk] Heard but command isn't configured yet")

        return False

    def audio_callback(self, indata, _, __, status):
        if status:
            print(status, file=sys.stderr)

        self.mic_queue.put(bytes(indata))

    # Main vosk loop to convert audio to text form.
    async def vosk_mic_worker(self) -> None:
        print("[Vosk] Starting microphone listener...")

        try:
            with sd.RawInputStream(
                samplerate=SAMPLE_RATE,
                blocksize=8000,
                dtype="int16",
                channels=1,
                callback=self.audio_callback,
            ):
                while not self.shutdown_event.is_set():
                    loop = asyncio.get_running_loop()
                    is_ready = False

                    try:
                        data = self.mic_queue.get_nowait()
                        is_ready = await loop.run_in_executor(None, self.recognizer.AcceptWaveform, data)

                    except queue.Empty:
                        is_ready = False

                    if is_ready:
                        result = json.loads(self.recognizer.Result())
                        command = result.get("text", "").lower().strip()

                        if command:
                            print(f"[Vosk] Heard raw input: '{command}'")

                            if not self.is_awake:
                                if WAKE_WORD in command:
                                    print(f"[Vosk] Wake word '{WAKE_WORD}' detected.")
                                    remaining_command = command.replace(WAKE_WORD, "").strip()

                                    if remaining_command:
                                        print(f"[Vosk] Processing attached command: '{remaining_command}'")
                                        should_stop = await self.process_command(remaining_command)

                                        if should_stop:
                                            await self.discord_bot.initiate_shutdown("Voice command [stop]")
                                            break

                                    else:
                                        self.is_awake = True

                                else:
                                    print("[Vosk] Ignored command.")

                            else:
                                should_stop = await self.process_command(command)

                                if should_stop:
                                    await self.discord_bot.initiate_shutdown("[Vosk] Voice command \"quit\"")
                                    break

                            with self.mic_queue.mutex:
                                self.mic_queue.queue.clear()

                            self.recognizer.Reset()

                    await asyncio.sleep(0.01)

        except (asyncio.CancelledError, KeyboardInterrupt):
            print("[Vosk] Microphone loop cancelled. Cleaning up audio hardware...")
