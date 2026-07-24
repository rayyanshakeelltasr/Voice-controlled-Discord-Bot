import asyncio
import json
import discord

# Reads and loads the data from the configuration file
with open("config.json", "r") as file:
    config = json.load(file)

MY_USER_ID = config["MY_USER_ID"]
MY_SERVER_ID = config["MY_SERVER_ID"]

class DiscordBot:
    def __init__(self, shutdown_event: asyncio.Event) -> None:
        self.shutdown_event = shutdown_event
        self.intents = discord.Intents.all()
        self.intents.message_content = True
        self.client = discord.Client(intents=self.intents)
        self._register_events()

    async def list_users_in_vc(self) -> list:
        guild = self.client.get_guild(MY_SERVER_ID)

        if not guild:
            print("[Discord] Server was not found in cache. Trying to fetch from API...")

            try:
                guild = await self.client.fetch_guild(MY_SERVER_ID)
            except Exception:
                print("[Discord] Failed to fetch the server from Discord API")
                return []
            
        voice_channel = None

        try:
            member = guild.get_member(MY_USER_ID)

            if not member:
                print("[Discord] Member not in cache. Fetching from API...")
                member = await guild.fetch_member(MY_USER_ID)

            if member and member.voice and member.voice.channel:
                voice_channel = member.voice.channel
            else:
                print("[Discord] User is not in a voice channel")

        except discord.NotFound:
            print("[Discord] The user specified does not exist in that server")
        except Exception as e:
            print(f"[Discord] Error fetching user {e}")

        users_in_vc = []

        if voice_channel:
            users_in_vc = [user.id for user in voice_channel.members]
        else:
            print("[Discord] Voice channel does not exist")

        return users_in_vc

    def _parse_command(self, message_content: str) -> tuple[str, int | None]:
        parts = message_content.strip().split()

        if not parts:
            return "", None

        command = parts[0].lower()
        target_index = None

        if len(parts) > 1:
            try:
                target_index = int(parts[1])
            except ValueError:
                return command, None

        return command, target_index

    def _register_events(self) -> None:
        @self.client.event
        async def on_ready() -> None:
            print(f"[Discord] Logged in as {self.client.user}")
            await self.send_direct_message(MY_USER_ID, "**System online**")

        @self.client.event
        async def on_message(message: discord.Message) -> None:
            if message.author == self.client.user or message.author.id != MY_USER_ID:
                return

            print(f"[Discord] Recieved message \"{message.content}\"")

            command, target_index = self._parse_command(message.content)

            if not command:
                return

            if command in {"kick", "mute", "deafen"}:
                if target_index is None:
                    await self.send_direct_message(MY_USER_ID, "Please provide a numeric target index for that command.")
                    return

                target_list = await self.list_users_in_vc()

                if not 0 <= target_index < len(target_list):
                    await self.send_direct_message(MY_USER_ID, f"Invalid target index {target_index}.")
                    return

                target = target_list[target_index]

            if command == "quit":
                await self.initiate_shutdown("DM command [quit]")

            elif command == "kick":
                await self.vc_kick(MY_SERVER_ID, target)

            elif command == "mute":
                await self.vc_mute(MY_SERVER_ID, target)

            elif command == "deafen":
                await self.vc_deafen(MY_SERVER_ID, target)

            elif command == "list":
                print(await self.list_users_in_vc())
                await self.send_direct_message(MY_USER_ID, "Printed list of users in Terminal")

    async def send_direct_message(self, userid: int, message: str) -> None:
        print(f"[Discord] Sending DM to user {userid}: {message}")

        try:
            user = self.client.get_user(userid) or await self.client.fetch_user(userid)
            await user.send(message)
            print("[Discord] DM sent successfully.")

        except Exception as e:
            print(f"[Discord] Failed to send DM: {e}")

    async def on_closed(self) -> None:
        if self.client.is_ready() and not self.client.is_closed():
            await self.send_direct_message(MY_USER_ID, "**System offline**")

        else:
            print("[Discord] Skipping offline DM because client is not ready or already closed.")

    async def modify_user_state(self, guild_id: int, user_id: int, **kwargs) -> None:
        if self.client.is_closed():
            return

        try:
            server = self.client.get_guild(guild_id) or await self.client.fetch_guild(guild_id)
            member = await server.fetch_member(user_id)

            if member.voice and member.voice.channel:
                await member.edit(**kwargs)
                print(f"[Discord] Updated voice state: {kwargs}")

            else:
                print(f"[Discord] {member} is not in a voice chat.")

        except discord.NotFound:
            print(f"[Discord] Could not find guild {guild_id} or user {user_id}.")

        except discord.Forbidden:
            print("[Discord] Bot lacks permissions to modify voice state.")

        except Exception as e:
            print(f"[Discord] Network operation failed: {e}")

    async def vc_kick(self, guild_id: int, user_id: int) -> None:
        await self.modify_user_state(guild_id, user_id, voice_channel=None)

    async def vc_mute(self, guild_id: int, user_id: int) -> None:
        await self.modify_user_state(guild_id, user_id, mute=True)

    async def vc_deafen(self, guild_id: int, user_id: int) -> None:
        await self.modify_user_state(guild_id, user_id, deafen=True)

    async def initiate_shutdown(self, reason: str) -> None:
        if self.shutdown_event.is_set():
            return

        print(f"Shutdown triggered by {reason}")
        self.shutdown_event.set()

        if self.client.is_ready() and not self.client.is_closed():
            try:
                await self.on_closed()

            except Exception as e:
                print(f"[System] on_closed error during shutdown: {e}")

        if not self.client.is_closed():
            await self.client.close()
