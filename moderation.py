import json
import time
from datetime import datetime

LOG_FILE = "mod_logs.json"

# Sabit mod listesi (küçük harfli kullanıcı adları)
MOD_LIST = {"mod1", "mod2", "atknz"}  # Buraya modları ekle

def load_logs():
    try:
        with open(LOG_FILE, "r") as f:
            return json.load(f)
    except:
        return {"mute": [], "kick": [], "ban": [], "unmute": [], "unban": []}

def save_logs(logs):
    with open(LOG_FILE, "w") as f:
        json.dump(logs, f, indent=2)

async def handle_mod_command(bot, user, message: str):
    if not message.startswith("!"):
        return False

    command_parts = message.strip().split()
    cmd = command_parts[0][1:].lower()
    args = command_parts[1:]

    if user.username.lower() not in MOD_LIST:
        return False

    if cmd == "mute":
        if len(args) < 3:
            await bot.highrise.send_whisper(user.id, "Kullanım: !mute @kullanici süre_dk sebep")
            return True
        target_name = args[0].lstrip("@").lower()
        try:
            duration = int(args[1])
        except:
            await bot.highrise.send_whisper(user.id, "Süre dakika cinsinden olmalıdır.")
            return True
        reason = " ".join(args[2:])
        await mute_user(bot, user, target_name, duration, reason)
        return True

    if cmd == "unmute":
        if len(args) < 1:
            await bot.highrise.send_whisper(user.id, "Kullanım: !unmute @kullanici")
            return True
        target_name = args[0].lstrip("@").lower()
        await unmute_user(bot, user, target_name)
        return True

    if cmd == "kick":
        if len(args) < 1:
            await bot.highrise.send_whisper(user.id, "Kullanım: !kick @kullanici")
            return True
        target_name = args[0].lstrip("@").lower()
        await kick_user(bot, user, target_name)
        return True

    if cmd == "ban":
        if len(args) < 1:
            await bot.highrise.send_whisper(user.id, "Kullanım: !ban @kullanici [süre_dk]")
            return True
        target_name = args[0].lstrip("@").lower()
        ban_duration = None
        if len(args) >= 2:
            try:
                ban_duration = int(args[1])
            except:
                await bot.highrise.send_whisper(user.id, "Süre dakika cinsinden olmalıdır.")
                return True
        await ban_user(bot, user, target_name, ban_duration)
        return True

    if cmd == "unban":
        if len(args) < 1:
            await bot.highrise.send_whisper(user.id, "Kullanım: !unban @kullanici")
            return True
        target_name = args[0].lstrip("@").lower()
        await unban_user(bot, user, target_name)
        return True

    if cmd == "log":
        if len(args) < 1:
            await bot.highrise.send_whisper(user.id, "Kullanım: !log mute/kick/ban/unmute/unban")
            return True
        log_type = args[0].lower()
        if log_type not in ["mute", "kick", "ban", "unmute", "unban"]:
            await bot.highrise.send_whisper(user.id, "Geçersiz log türü. mute/kick/ban/unmute/unban")
            return True
        await send_log(bot, user, log_type)
        return True

    return False

async def mute_user(bot, mod_user, target_name, duration_minutes, reason):
    try:
        response = await bot.highrise.get_room_users()
        users = [content[0] for content in response.content]
    except Exception as e:
        await bot.highrise.send_whisper(mod_user.id, f"Kullanıcılar alınamadı: {e}")
        return

    target_user = next((u for u in users if u.username.lower() == target_name), None)
    if not target_user:
        await bot.highrise.send_whisper(mod_user.id, f"{target_name} bulunamadı.")
        return

    try:
        await bot.highrise.mute_user(target_user.id)
        # Mute bitiş zamanını main.py'deki mute süresi dictine ekle
        bot.muted_users[target_user.id] = time.time() + duration_minutes * 60
        await bot.highrise.send_whisper(mod_user.id, f"{target_user.username} {duration_minutes} dakika susturuldu.")
    except Exception as e:
        await bot.highrise.send_whisper(mod_user.id, f"Mute işlemi başarısız: {e}")
        return

    log_entry = {
        "mod": mod_user.username,
        "target": target_user.username,
        "action": "mute",
        "reason": reason,
        "duration_minutes": duration_minutes,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    logs = load_logs()
    if "mute" not in logs:
        logs["mute"] = []
    logs["mute"].append(log_entry)
    save_logs(logs)

async def unmute_user(bot, mod_user, target_name):
    try:
        response = await bot.highrise.get_room_users()
        users = [content[0] for content in response.content]
    except Exception as e:
        await bot.highrise.send_whisper(mod_user.id, f"Kullanıcılar alınamadı: {e}")
        return

    target_user = next((u for u in users if u.username.lower() == target_name), None)
    if not target_user:
        await bot.highrise.send_whisper(mod_user.id, f"{target_name} bulunamadı.")
        return

    try:
        await bot.highrise.unmute_user(target_user.id)
        # Mute listesinden kaldır
        if target_user.id in bot.muted_users:
            del bot.muted_users[target_user.id]
        await bot.highrise.send_whisper(mod_user.id, f"{target_user.username} susturması kaldırıldı.")
    except Exception as e:
        await bot.highrise.send_whisper(mod_user.id, f"Unmute işlemi başarısız: {e}")
        return

    log_entry = {
        "mod": mod_user.username,
        "target": target_user.username,
        "action": "unmute",
        "reason": None,
        "duration_minutes": None,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    logs = load_logs()
    if "unmute" not in logs:
        logs["unmute"] = []
    logs["unmute"].append(log_entry)
    save_logs(logs)

async def kick_user(bot, mod_user, target_name):
    try:
        response = await bot.highrise.get_room_users()
        users = [content[0] for content in response.content]
    except Exception as e:
        await bot.highrise.send_whisper(mod_user.id, f"Kullanıcılar alınamadı: {e}")
        return

    target_user = next((u for u in users if u.username.lower() == target_name), None)
    if not target_user:
        await bot.highrise.send_whisper(mod_user.id, f"{target_name} bulunamadı.")
        return

    try:
        await bot.highrise.kick_user(target_user.id)
        await bot.highrise.send_whisper(mod_user.id, f"{target_user.username} atıldı.")
    except Exception as e:
        await bot.highrise.send_whisper(mod_user.id, f"Kick işlemi başarısız: {e}")
        return

    log_entry = {
        "mod": mod_user.username,
        "target": target_user.username,
        "action": "kick",
        "reason": None,
        "duration_minutes": None,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    logs = load_logs()
    if "kick" not in logs:
        logs["kick"] = []
    logs["kick"].append(log_entry)
    save_logs(logs)

async def ban_user(bot, mod_user, target_name, duration_minutes=None):
    try:
        response = await bot.highrise.get_room_users()
        users = [content[0] for content in response.content]
    except Exception as e:
        await bot.highrise.send_whisper(mod_user.id, f"Kullanıcılar alınamadı: {e}")
        return

    target_user = next((u for u in users if u.username.lower() == target_name), None)
    if not target_user:
        await bot.highrise.send_whisper(mod_user.id, f"{target_name} bulunamadı.")
        return

    try:
        if duration_minutes:
            await bot.highrise.ban_user(target_user.id, duration_minutes)
            await bot.highrise.send_whisper(mod_user.id, f"{target_user.username} {duration_minutes} dakika banlandı.")
        else:
            await bot.highrise.ban_user(target_user.id)
            await bot.highrise.send_whisper(mod_user.id, f"{target_user.username} kalıcı banlandı.")
    except Exception as e:
        await bot.highrise.send_whisper(mod_user.id, f"Ban işlemi başarısız: {e}")
        return

    log_entry = {
        "mod": mod_user.username,
        "target": target_user.username,
        "action": "ban",
        "reason": None,
        "duration_minutes": duration_minutes,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    logs = load_logs()
    if "ban" not in logs:
        logs["ban"] = []
    logs["ban"].append(log_entry)
    save_logs(logs)

async def unban_user(bot, mod_user, target_name):
    await bot.highrise.send_whisper(mod_user.id, f"Unban komutu henüz implementasyona eklenecek.")

async def send_log(bot, mod_user, log_type):
    logs = load_logs()
    if log_type not in logs or not logs[log_type]:
        await bot.highrise.send_whisper(mod_user.id, f"{log_type} logları boş.")
        return

    log_entries = logs[log_type][-5:]  # Son 5 kayıt
    message = f"Son {log_type} logları:\n"
    for entry in log_entries:
        message += f"{entry['timestamp']} - {entry['mod']} -> {entry['target']}\n"

    await bot.highrise.send_whisper(mod_user.id, message)