import asyncio
import datetime
import io
import os
import re
import subprocess

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import psutil
import docker
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message, BufferedInputFile
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

bot = Bot(token=str(BOT_TOKEN))
dp = Dispatcher()


def get_bot_health():
    """Одна строка на каждый tracked-юнит: состояние, аптайм, рестарты, ошибки за час."""
    lines = []
    for unit in ("snootsbot",):
        try:
            props = {}
            out = subprocess.run(
                ["systemctl", "show", unit,
                 "-p", "ActiveState", "-p", "NRestarts", "-p", "ExecMainStartTimestamp"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            for line in out.splitlines():
                key, _, val = line.partition("=")
                props[key] = val
            errs = subprocess.run(
                ["journalctl", "-u", unit, "-p", "err", "--since", "1 hour ago", "--no-pager"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            start = " ".join(props.get("ExecMainStartTimestamp", "").split()[1:3])
            errors = len([l for l in errs.splitlines() if "No entries" not in l])
            lines.append(
                f"🤖 {unit}: {props.get('ActiveState', '?')}"
                f", up since {start or '?'}"
                f", restarts: {props.get('NRestarts', '?')}"
                f", errors (1h): {errors}"
            )
        except Exception as e:
            lines.append(f"🤖 {unit}: check failed ({e})")
    return "\n".join(lines)


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
        f"Names: <code>{container_names}</code>\n"
        f"{get_bot_health()}"
    )


def build_graph(per_hour: dict):
    now = datetime.datetime.now()
    hours = [now - datetime.timedelta(hours=k) for k in range(23, -1, -1)]
    counts = [per_hour.get(h.strftime("%Y-%m-%dT%H"), 0) for h in hours]
    fig, ax = plt.subplots(figsize=(10, 2.6), dpi=100)
    ax.bar(range(len(counts)), counts, color="#d64545")
    ax.set_xticks(range(len(counts)))
    ax.set_xticklabels([h.strftime("%H") for h in hours], fontsize=7)
    ax.set_title("Failed ssh attempts, last 24h", fontsize=9)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def get_bruteforce():
    try:
        out = subprocess.run(
            ["journalctl", "-u", "ssh", "-u", "sshd", "--since", "24 hours ago", "--no-pager", "-o", "short-iso"],
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout
    except Exception as e:
        return f"Logins unavailable: {e}", None

    brute = re.compile(r"Failed password|Invalid user|Connection closed by authenticating user", re.I)
    ips = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
    per_hour = {}
    unique_ips = set()
    total = 0
    for line in out.splitlines():
        if brute.search(line):
            total += 1
            per_hour[line[:13]] = per_hour.get(line[:13], 0) + 1
            unique_ips.update(ips.findall(line))

    if not total:
        return "No brute-force attempts in the last 24h", None
    return (
        f"🛡 Brute-force attempts (24h): {total} from {len(unique_ips)} IPs",
        build_graph(per_hour),
    )


async def send_stats():
    text, png = get_bruteforce()
    report = f"{get_server_stats()}\n\n{text}"
    if png:
        await bot.send_photo(chat_id=str(ADMIN_ID), photo=BufferedInputFile(png, filename="bruteforce.png"), caption=report, parse_mode="HTML")
    else:
        await bot.send_message(chat_id=str(ADMIN_ID), text=report)


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
    text, png = get_bruteforce()
    if png:
        await message.answer_photo(BufferedInputFile(png, filename="bruteforce.png"), caption=text)
    else:
        await message.answer(text)


async def main():
    scheduler = AsyncIOScheduler(timezone='Europe/Moscow')
    scheduler.add_job(send_stats, trigger='interval', hours=1)
    scheduler.start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())