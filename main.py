import asyncio
import json
import os
import sys

from dotenv import load_dotenv

CONFIG_FILE = "config.json"
REQUIRED_CONFIG_FIELDS = ("MY_USER_ID", "MY_SERVER_ID", "WAKE_WORD", "VOSK_MODEL_PATH")

def validate_required_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        print(f"[System] Config file '{CONFIG_FILE}' was not found. Please create it before starting the bot.")
        sys.exit(1)

    try:
        with open(CONFIG_FILE, "r") as file:
            config = json.load(file)

    except json.JSONDecodeError as error:
        print(f"[System] Could not read '{CONFIG_FILE}': {error}")
        sys.exit(1)

    missing_fields = []

    for field in REQUIRED_CONFIG_FIELDS:
        value = config.get(field)

        if value in (None, "", 0):
            missing_fields.append(field)

    if missing_fields:
        print("[System] The following required config values are missing or invalid:")
        for field in missing_fields:
            print(f" - {field}")
        print("[System] Please update config.json before starting the Discord bot and Vosk.")
        print("[System] Please also read the README for further information, it would make it easier to use!")
        sys.exit(1)

    return config

validate_required_config()

from discord_bot import DiscordBot
from vosk_worker import VoskWorker

load_dotenv()

if not load_dotenv():
    print("[System] Could not find Environment file or file is empty")
    sys.exit(1)

async def main() -> None:
    shutdown_event = asyncio.Event()
    discord_bot = DiscordBot(shutdown_event)
    vosk_worker = VoskWorker(shutdown_event, discord_bot)

    vosk_task = asyncio.create_task(vosk_worker.vosk_mic_worker())

    try:
        async with discord_bot.client:
            token = os.getenv("DISCORD_BOT_TOKEN")

            if not token:
                print("[System] No Discord token found. Set DISCORD_BOT_TOKEN or create token.txt")
                return

            client_task = asyncio.create_task(discord_bot.client.start(token))
            shutdown_task = asyncio.create_task(shutdown_event.wait())
            done, pending = await asyncio.wait(
                [client_task, shutdown_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            if shutdown_event.is_set():
                try:
                    await asyncio.wait_for(client_task, timeout=2.0)

                except asyncio.TimeoutError:
                    if not discord_bot.client.is_closed():
                        await discord_bot.client.close()

                if shutdown_task in pending:
                    shutdown_task.cancel()
                    await asyncio.gather(shutdown_task, return_exceptions=True)

            else:
                if shutdown_task in pending:
                    shutdown_task.cancel()
                    await asyncio.gather(shutdown_task, return_exceptions=True)

            await asyncio.gather(vosk_task, return_exceptions=True)

    except Exception:
        import traceback

        print("[System] Exception in main:")
        traceback.print_exc()

    finally:
        print("[System] Shutting down remaining async workers...")
        vosk_task.cancel()
        await asyncio.gather(vosk_task, return_exceptions=True)
        print("[System] All systems stopped successfully.")


if __name__ == "__main__":
    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        print("\n[System] Manual terminal interrupt caught. Closing.")