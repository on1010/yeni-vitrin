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

        # Bot ayarları dosyası
        self.settings_file = "bot_settings.json"
        self.settings = {}
        self.load_settings()

        # Loop task için değişkenler
        self.loop_message_task = None
        self.loop_message = ""
        self.loop_interval = 0
        
        # Bot user ID
        self.bot_user_id = None

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

    def load_settings(self):
        if os.path.isfile(self.settings_file):
            try:
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    self.settings = json.load(f)
            except Exception as e:
                print("Settings yüklenirken hata:", e)
                self.settings = {}
        else:
            self.settings = {}

    def save_settings(self):
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("Settings kaydedilirken hata:", e)

    async def on_start(self, session_metadata: SessionMetadata) -> None:
        print("Bot başladı, odada hazır.")
        self.bot_user_id = session_metadata.user_id
        
        # Kaydedilmiş pozisyona teleport et
        saved_position = self.settings.get("bot_position")
        if saved_position:
            try:
                position = Position(
                    saved_position["x"], 
                    saved_position["y"], 
                    saved_position["z"], 
                    saved_position["facing"]
                )
                await self.highrise.teleport(self.bot_user_id, position)
                print(f"Bot kaydedilmiş pozisyona teleport edildi: {saved_position}")
            except Exception as e:
                print(f"Teleport hatası: {e}")

        # Odada mevcut olan kullanıcıları kontrol et ve join_time'ını ayarla
        try:
            room_users = (await self.highrise.get_room_users()).content
            now = time.time()
            for room_user, position in room_users:
                user = room_user
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
            self.save_stats()
            print(f"Bot başladığında {len(room_users)} kullanıcının süresi takip edilmeye başlandı.")
        except Exception as e:
            print(f"Mevcut kullanıcıları yüklerken hata: {e}")

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

        # Hoşgeldin mesajı gönder (eğer ayarlanmışsa)
        welcome_message = self.settings.get("welcome_message")
        if welcome_message:
            await self.highrise.chat(welcome_message.replace("{username}", user.username))

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

        if msg_lower == "!emotelist":
            await self.send_emotelist(user_id)
            return

        if msg_lower.startswith("!setwelcome"):
            if await self.is_user_allowed(user):
                welcome_text = message.strip()[11:].strip()  # "!setwelcome" kısmını çıkar
                if welcome_text:
                    self.settings["welcome_message"] = welcome_text
                    self.save_settings()
                    await self.highrise.send_whisper(user_id, f"Hoşgeldin mesajı ayarlandı: {welcome_text}")
                else:
                    # Hoşgeldin mesajını kaldır
                    if "welcome_message" in self.settings:
                        del self.settings["welcome_message"]
                        self.save_settings()
                    await self.highrise.send_whisper(user_id, "Hoşgeldin mesajı kaldırıldı.")
            else:
                await self.highrise.send_whisper(user_id, "Bu komutu kullanma yetkiniz yok.")
            return

        if msg_lower.startswith("!loop"):
            if await self.is_user_allowed(user):
                parts = message.strip().split(" ", 2)
                if len(parts) >= 3:
                    try:
                        interval = int(parts[1])
                        loop_text = parts[2]
                        
                        # Önceki loop'u durdur
                        if self.loop_message_task and not self.loop_message_task.done():
                            self.loop_message_task.cancel()
                        
                        self.loop_interval = interval
                        self.loop_message = loop_text
                        self.loop_message_task = asyncio.create_task(self.message_loop())
                        
                        await self.highrise.send_whisper(user_id, f"Loop başlatıldı: Her {interval} saniyede '{loop_text}' yazılacak.")
                    except ValueError:
                        await self.highrise.send_whisper(user_id, "Geçersiz saniye değeri. Örnek: !loop 10 Mesajınız")
                elif len(parts) == 1:
                    # Loop'u durdur
                    if self.loop_message_task and not self.loop_message_task.done():
                        self.loop_message_task.cancel()
                        self.loop_message = ""
                        self.loop_interval = 0
                        await self.highrise.send_whisper(user_id, "Loop durduruldu.")
                    else:
                        await self.highrise.send_whisper(user_id, "Aktif loop bulunamadı.")
                else:
                    await self.highrise.send_whisper(user_id, "Kullanım: !loop <saniye> <mesaj> veya !loop (durdurmak için)")
            else:
                await self.highrise.send_whisper(user_id, "Bu komutu kullanma yetkiniz yok.")
            return

        if msg_lower == "!bots":
            if await self.is_user_allowed(user):
                # Kullanıcının pozisyonunu al
                try:
                    room_users = (await self.highrise.get_room_users()).content
                    user_position = None
                    
                    for room_user, position in room_users:
                        if room_user.id == user_id:
                            user_position = position
                            break
                    
                    if user_position:
                        # Botun pozisyonunu kullanıcının pozisyonuna ayarla
                        await self.highrise.teleport(self.bot_user_id, user_position)
                        
                        # Pozisyonu kaydet
                        position_data = {
                            "x": user_position.x,
                            "y": user_position.y, 
                            "z": user_position.z,
                            "facing": user_position.facing
                        }
                        self.settings["bot_position"] = position_data
                        self.save_settings()
                        
                        await self.highrise.send_whisper(user_id, f"Bot pozisyonu ayarlandı: x={user_position.x:.1f}, y={user_position.y:.1f}, z={user_position.z:.1f}")
                    else:
                        await self.highrise.send_whisper(user_id, "Pozisyonunuz alınamadı.")
                        
                except Exception as e:
                    await self.highrise.send_whisper(user_id, f"Bot pozisyonu ayarlanırken hata: {e}")
            else:
                await self.highrise.send_whisper(user_id, "Bu komutu kullanma yetkiniz yok.")
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

        # Kombinasyon skoru hesapla: (dakika/10 + mesaj sayısı)
        def calculate_score(data):
            total_minutes = data.get("total_time", 0) / 60  # saniyeyi dakikaya çevir
            msg_count = data.get("msg_count", 0)
            return (total_minutes / 10) + msg_count

        # En iyi 5 kullanıcıyı kombinasyon skoruna göre sırala
        sorted_users = sorted(
            self.user_stats.items(),
            key=lambda x: calculate_score(x[1]),
            reverse=True
        )

        medals = ["🥇", "🥈", "🥉"]
        lines = ["🏆 Lider Tablosu (Dakika+Mesaj) 🏆\n"]

        for i, (uid, data) in enumerate(sorted_users[:5]):
            medal = medals[i] if i < 3 else f"{i+1}."
            total_seconds = int(data.get("total_time", 0))
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            time_str = f"{hours}s {minutes}dk" if hours > 0 else f"{minutes}dk"
            score = calculate_score(data)
            lines.append(f"{medal} {data.get('username','?')} — {time_str} — {data.get('msg_count',0)} mesaj — Skor: {score:.1f}")

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

        # Kombinasyon skoru hesapla
        def calculate_score(data):
            total_minutes = data.get("total_time", 0) / 60
            msg_count = data.get("msg_count", 0)
            return (total_minutes / 10) + msg_count

        # Mevcut kullanıcının skorunu hesapla
        user_score = (total_time / 60 / 10) + msg_count

        # Sıralamayı hesapla (yeni skor sistemine göre)
        sorted_users = sorted(
            self.user_stats.items(),
            key=lambda x: calculate_score(x[1]),
            reverse=True
        )

        rank = next((i+1 for i, (uid, _) in enumerate(sorted_users) if uid == user_id), None)
        rank_str = f"{rank}. sıra" if rank else "Sıralamada yok"

        time_str = f"{hours} saat {minutes} dk" if hours > 0 else f"{minutes} dk"
        message = (
            f"📊 İstatistiklerin:\n"
            f"💬 Mesaj sayısı: {msg_count}\n"
            f"⏱️ Toplam süre: {time_str}\n"
            f"🎯 Kombinasyon skoru: {user_score:.1f}\n"
            f"🏆 Sıralama: {rank_str}"
        )

        await self.highrise.send_whisper(user_id, message)

    async def send_emotelist(self, user_id: str):
        # emote_mapping'den emote isimlerini al
        emote_names = []
        for key in emote_mapping.keys():
            # Sayı anahtarlarını atla, sadece isim anahtarlarını al
            if not key.isdigit():
                emote_names.append(key)
        
        # Alfabetik sıraya koy
        emote_names.sort()
        
        # Emote isimlerini sayfalara böl (her sayfada maksimum 20 emote)
        page_size = 20
        pages = [emote_names[i:i + page_size] for i in range(0, len(emote_names), page_size)]
        
        # Her sayfayı ayrı mesaj olarak gönder
        for i, page in enumerate(pages):
            message = f"🎭 Emote Listesi ({i+1}/{len(pages)}) 🎭\n\n"
            message += ", ".join(page)
            
            # Fısıldama ile gönder
            await self.highrise.send_whisper(user_id, message)
            
            # Sayfa arası kısa bekleme
            await asyncio.sleep(0.5)

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

    async def message_loop(self):
        while True:
            try:
                if not self.loop_message or self.loop_interval <= 0:
                    break
                await self.highrise.chat(self.loop_message)
                await asyncio.sleep(self.loop_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Message loop hatası: {e}")
                await asyncio.sleep(5)

    # Diğer boş fonksiyonlar örneğin:
    async def on_user_move(self, user: User, pos: Position) -> None:
        pass

    async def on_whisper(self, user: User, message: str) -> None:
        pass

    async def is_user_allowed(self, user: User) -> bool:
        try:
            user_privileges = await self.highrise.get_room_privilege(user.id)
            return user_privileges.moderator or user.username in ["Atknz", "Hernuell"]
        except Exception as e:
            print(f"Yetki kontrolü hatası: {e}")
            return user.username in ["Atknz"]


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
    room_id = "685fe9208ab075915779c70e"
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
    