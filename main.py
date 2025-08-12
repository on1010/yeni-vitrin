import asyncio
import time
import json
import os
import random
from importlib import import_module
from threading import Thread
from flask import Flask

from highrise import *
from highrise.models import *
from highrise.__main__ import main as hr_main, BotDefinition  # highrise ana async main fonksiyonu
from emotes import emote_mapping, secili_emote, paid_emotes  # emote sözlükleri

class Bot(BaseBot):
    def __init__(self):
        super().__init__()

        # Kullanıcı emote döngüleri {user_id: emote_name}
        self.user_emote_loops = {}
        self.loop_task = None

        # İstatistik verisi: { user_id: { 'join_time': float, 'total_time': float, 'msg_count': int, 'username': str } }
        self.user_stats = {}

        # Kalıcı veri dosyası
        self.stats_file = "user_stats.json"
        self.load_stats()

    def load_stats(self):
        if os.path.isfile(self.stats_file):
            try:
                with open(self.stats_file, "r") as f:
                    self.user_stats = json.load(f)
                # join_time sıfırlansın (anlık)
                for u in self.user_stats.values():
                    u["join_time"] = None
            except Exception as e:
                print("Stats yüklenirken hata:", e)
                self.user_stats = {}
        else:
            self.user_stats = {}

    def save_stats(self):
        try:
            # join_time bilgisi kaydedilmez (runtime only)
            data_to_save = {}
            for uid, data in self.user_stats.items():
                data_to_save[uid] = {
                    "total_time": data.get("total_time", 0),
                    "msg_count": data.get("msg_count", 0),
                    "username": data.get("username", "")
                }
            with open(self.stats_file, "w") as f:
                json.dump(data_to_save, f)
        except Exception as e:
            print("Stats kaydedilirken hata:", e)

    async def on_start(self, session_metadata: SessionMetadata) -> None:
        print("Bot başladı, odada hazır.")
        # Örnek teleport, istersen kaldırabilirsin
        await self.highrise.tg.create_task(self.highrise.teleport(
            session_metadata.user_id, Position(9.0, 0.25, 0.5, "FrontRight")))

        # Emote loop başlat
        if self.loop_task is None or self.loop_task.done():
            self.loop_task = asyncio.create_task(self.emote_loop())

    async def emote_loop(self):
        while True:
            try:
                emote_name = random.choice(list(paid_emotes.keys()))
                emote_to_send = paid_emotes[emote_name]["value"]
                emote_time = paid_emotes[emote_name]["time"]

                await self.highrise.send_emote(emote_to_send)
                await asyncio.sleep(emote_time)
            except Exception as e:
                print("Emote döngüsünde hata:", e)
                await asyncio.sleep(5)

    async def on_user_join(self, user: User, position: Position | AnchorPosition) -> None:
        now = time.time()
        if user.id not in self.user_stats:
            self.user_stats[user.id] = {
                "join_time": now,
                "total_time": 0,
                "msg_count": 0,
                "username": user.username
            }
        else:
            self.user_stats[user.id]["join_time"] = now
            self.user_stats[user.id]["username"] = user.username

        # Rastgele karşılama emote'u gönder
        try:
            emote_name = random.choice(list(secili_emote.keys()))
            emote_info = secili_emote[emote_name]
            await self.send_emote(emote_info["value"], user.id)
        except Exception as e:
            print(f"Join emote gönderilemedi: {e}")

        self.save_stats()

    async def on_user_leave(self, user: User):
        # Oturum süresini güncelle
        stat = self.user_stats.get(user.id)
        if stat and stat.get("join_time"):
            session_time = time.time() - stat["join_time"]
            stat["total_time"] = stat.get("total_time", 0) + session_time
            stat["join_time"] = None
            self.save_stats()

        # Emote döngüsünü durdur
        if user.id in self.user_emote_loops:
            await self.stop_emote_loop(user.id)

    async def on_chat(self, user: User, message: str) -> None:
        user_id = user.id
        msg_lower = message.strip().lower()

        # Kullanıcı istatistiklerini güncelle
        if user_id not in self.user_stats:
            self.user_stats[user_id] = {"join_time": None, "total_time": 0, "msg_count": 1, "username": user.username}
        else:
            self.user_stats[user_id]["msg_count"] = self.user_stats[user_id].get("msg_count", 0) + 1
            self.user_stats[user_id]["username"] = user.username
        self.save_stats()

        # Komutlar:
        if msg_lower == "!stats":
            await self.send_stats(user_id)
            return

        if msg_lower == "!mytime":
            await self.send_mytime(user_id)
            return

        if msg_lower.startswith("full"):
            emote_name = msg_lower.replace("full", "").strip()
            if user_id in self.user_emote_loops and self.user_emote_loops[user_id] == emote_name:
                await self.stop_emote_loop(user_id)
            else:
                await self.start_emote_loop(user_id, emote_name)
            return

        if msg_lower in ["stop", "dur", "0"]:
            if user_id in self.user_emote_loops:
                await self.stop_emote_loop(user_id)
            return

        if msg_lower == "ulti":
            if user_id not in self.user_emote_loops:
                await self.start_random_emote_loop(user_id)
            return

        # !unban @username komutu moderation modülünde olacak, burada değil.

        # Diğer emote komutları (tek seferlik)
        if msg_lower in emote_mapping:
            emote_to_send = emote_mapping[msg_lower]["value"]
            try:
                await self.highrise.send_emote(emote_to_send, user_id)
            except Exception as e:
                print(f"Emote gönderilemedi: {e}")
            return

        # all <emote> komutu
        if msg_lower.startswith("all "):
            emote_name = msg_lower.replace("all ", "").strip()
            if emote_name in emote_mapping:
                emote_to_send = emote_mapping[emote_name]["value"]
                room_users = (await self.highrise.get_room_users()).content
                tasks = [self.highrise.send_emote(emote_to_send, ru[0].id) for ru in room_users]
                try:
                    await asyncio.gather(*tasks)
                except Exception as e:
                    await self.highrise.send_whisper(user.id, f"Emote gönderirken hata: {e}")
            else:
                await self.highrise.send_whisper(user.id, f"Geçersiz emote: {emote_name}")
            return

        # Dans komutu örneği
        if msg_lower.startswith("dans") or msg_lower.startswith("dance"):
            try:
                emote_name = random.choice(list(secili_emote.keys()))
                emote_to_send = secili_emote[emote_name]["value"]
                await self.highrise.send_emote(emote_to_send, user_id)
            except Exception:
                print("Dans emote gönderilirken hata oluştu.")
            return

    async def send_stats(self, requester_id: str):
        # Şu anki oturum sürelerini güncelle (odada olanlar için)
        now = time.time()
        for uid, data in self.user_stats.items():
            if data.get("join_time"):
                session_time = now - data["join_time"]
                data["total_time"] = data.get("total_time", 0) + session_time
                data["join_time"] = now
        self.save_stats()

        # En iyi 5 kullanıcıyı mesaj ve süreye göre sırala
        sorted_users = sorted(
            self.user_stats.items(),
            key=lambda x: (x[1].get("msg_count", 0), x[1].get("total_time", 0)),
            reverse=True
        )

        medals = ["🥇", "🥈", "🥉"]
        lines = ["🏆 **Lider Tablosu** 🏆\n"]

        for i, (uid, data) in enumerate(sorted_users[:5]):
            medal = medals[i] if i < 3 else f"{i+1}."
            total_seconds = int(data.get("total_time", 0))
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            time_str = f"{hours} saat {minutes} dk" if hours > 0 else f"{minutes} dk"
            lines.append(f"{medal} {data.get('username','?')} — {time_str} — {data.get('msg_count',0)} mesaj")

        leaderboard_message = "\n".join(lines)
        # Fısıldama ile gönder
        await self.highrise.send_whisper(requester_id, leaderboard_message)

    async def send_mytime(self, user_id: str):
        now = time.time()
        stat = self.user_stats.get(user_id)
        if not stat:
            await self.highrise.send_whisper(user_id, "Kayıtlı istatistik bulunamadı.")
            return

        total_time = stat.get("total_time", 0)
        join_time = stat.get("join_time")
        if join_time:
            total_time += (now - join_time)

        total_seconds = int(total_time)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60

        msg_count = stat.get("msg_count", 0)

        # Sıralamayı hesapla
        sorted_users = sorted(
            self.user_stats.items(),
            key=lambda x: (x[1].get("msg_count", 0), x[1].get("total_time", 0)),
            reverse=True
        )

        rank = next((i+1 for i, (uid, _) in enumerate(sorted_users) if uid == user_id), None)
        rank_str = f"{rank}. sıra" if rank else "Sıralamada yok"

        time_str = f"{hours} saat {minutes} dk" if hours > 0 else f"{minutes} dk"
        message = (
            f"İstatistiklerin:\n"
            f"Mesaj sayısı: {msg_count}\n"
            f"Toplam süre: {time_str}\n"
            f"Sıralama: {rank_str}"
        )

        await self.highrise.send_whisper(user_id, message)

    async def send_emote(self, emote_to_send: str, user_id: str) -> None:
        await self.highrise.send_emote(emote_to_send, user_id)

    async def start_emote_loop(self, user_id: str, emote_name: str):
        if emote_name not in emote_mapping:
            await self.highrise.send_whisper(user_id, f"Geçersiz emote: {emote_name}")
            return

        self.user_emote_loops[user_id] = emote_name
        emote_info = emote_mapping[emote_name]
        emote_to_send = emote_info["value"]
        emote_time = emote_info["time"]

        while self.user_emote_loops.get(user_id) == emote_name:
            try:
                await self.highrise.send_emote(emote_to_send, user_id)
            except Exception as e:
                if "Target user not in room" in str(e):
                    print(f"{user_id} odada değil, emote döngüsü durduruluyor.")
                    break
                else:
                    print(f"Emote gönderme hatası: {e}")
            await asyncio.sleep(emote_time)

    async def stop_emote_loop(self, user_id: str):
        if user_id in self.user_emote_loops:
            self.user_emote_loops.pop(user_id)

    async def start_random_emote_loop(self, user_id: str):
        self.user_emote_loops[user_id] = "ulti"
        while self.user_emote_loops.get(user_id) == "ulti":
            try:
                emote_name = random.choice(list(secili_emote.keys()))
                emote_info = secili_emote[emote_name]
                await self.highrise.send_emote(emote_info["value"], user_id)
                await asyncio.sleep(emote_info["time"])
            except Exception as e:
                print(f"Random emote döngüsü hatası: {e}")

    async def stop_random_emote_loop(self, user_id: str):
        if user_id in self.user_emote_loops and self.user_emote_loops[user_id] == "ulti":
            self.user_emote_loops.pop(user_id)

    # Diğer boş fonksiyonlar örneğin:
    async def on_user_move(self, user: User, pos: Position) -> None:
        pass

    async def on_whisper(self, user: User, message: str) -> None:
        pass

    async def is_user_allowed(self, user: User) -> bool:
        user_privileges = await self.highrise.get_room_privilege(user.id)
        return user_privileges.moderator or user.username in ["Atknz", ""]


class WebServer:
    def __init__(self):
        self.app = Flask(__name__)

        @self.app.route('/')
        def index():
            return "Alive"

    def run(self):
        self.app.run(host='0.0.0.0', port=8080)

    def keep_alive(self):
        t = Thread(target=self.run, daemon=True)
        t.start()

class RunBot:
    room_id = "675f21fcecbfd6b18c0474f3"
    bot_token = "96ecd496bcd8e8b3e75f54c9598dee120bb1cb0e28f8e7bcba0fc9ba274679dd"
    bot_file = "main"
    bot_class = "Bot"

    def __init__(self):
        self.definitions = [
            BotDefinition(
                getattr(import_module(self.bot_file), self.bot_class)(),
                self.room_id,
                self.bot_token
            )
        ]

    def run_loop(self):
        while True:
            try:
                asyncio.run(hr_main(self.definitions))
            except Exception as e:
                import traceback
                print("RunLoop hata yakaladı:")
                traceback.print_exc()
                time.sleep(5)


if __name__ == "__main__":
    WebServer().keep_alive()
    RunBot().run_loop()
    