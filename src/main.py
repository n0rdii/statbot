import asyncio
import html
import os
import re
import subprocess

import psutil
import docker
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

bot = Bot(token=str(BOT_TOKEN))
dp = Dispatcher()


def get_server_stats():
    load1, load5, load15 = os.getloadavg()
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')

    try:
        client = docker.from_env()
        containers = client.containers.list()
        running_count = len(containers)
        container_names = ", ".join([c.name for c in containers]) if containers else "No running"
    except Exception:
        running_count = "Access error"
        container_names = "Check Docker socket rights"

    return (
        f"📊 <b>Server stats</b>\n\n"
        f"<b>💻 CPU (Load):</b> {load1:.2f}, {load5:.2f}, {load15:.2f}\n"
        f"<b>🧠 RAM:</b> {mem.used / (1024 ** 3):.2f}GB / {mem.total / (1024 ** 3):.2f}GB ({mem.percent}%)\n"
        f"<b>💾 Disk:</b> {disk.used / (1024 ** 3):.2f}GB / {disk.total / (1024 ** 3):.2f}GB ({disk.percent}%)\n\n"
        f"🐳 <b>Docker:</b> Running {running_count}\n"
        f"Names: <code>{container_names}</code>"
    )


def get_logins():
    try:
        out = subprocess.run(
            ["journalctl", "-u", "ssh", "-u", "sshd", "--since", "24 hours ago", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout
    except Exception as e:
        return f"Logins unavailable: {e}"

    brute = re.compile(r"Failed password|Invalid user|Connection closed by authenticating user", re.I)
    ips = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
    counter = {}
    for line in out.splitlines():
        if brute.search(line):
            for ip in ips.findall(line):
                counter[ip] = counter.get(ip, 0) + 1

    if not counter:
        return "No brute-force attempts in the last 24h"
    top = "\n".join(
        f"{html.escape(ip)} — {n}"
        for ip, n in sorted(counter.items(), key=lambda i: -i[1])[:5]
    )
    return (
        f"🛡 Brute-force attempts (24h): {sum(counter.values())} from {len(counter)} IPs\n"
        f"Top sources:\n{top}"
    )


async def send_stats():
    text = f"{get_server_stats()}\n\n🔑 <b>Recent SSH events (24h)</b>\n{get_logins()}"
    await bot.send_message(chat_id=str(ADMIN_ID), text=text, parse_mode="HTML")


def admin_only(message: Message):
    return str(message.from_user.id) == ADMIN_ID


@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if not admin_only(message):
        return
    await message.answer(get_server_stats(), parse_mode="HTML")


@dp.message(Command("logins"))
async def cmd_logins(message: Message):
    if not admin_only(message):
        return
    await message.answer(get_logins())


async def main():
    scheduler = AsyncIOScheduler(timezone='Europe/Moscow')
    scheduler.add_job(send_stats, trigger='interval', hours=1)
    scheduler.start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())