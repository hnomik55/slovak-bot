"""Запуск Mini App с публичным HTTPS-адресом (Cloudflare Tunnel).

    python tools/miniapp_tunnel.py start    # сервер + туннель + прописать адрес в .env
    python tools/miniapp_tunnel.py status
    python tools/miniapp_tunnel.py stop

Что делает:
  1) поднимает Flask-сервер приложения на порту 8000;
  2) поднимает cloudflared и ждёт публичный адрес https://....trycloudflare.com;
  3) прописывает его в .env как WEBAPP_BASE_URL и перезапускает бота,
     чтобы кнопка «Открыть приложение» появилась в меню.

Адрес quick-туннеля меняется при каждом перезапуске — поэтому после перезагрузки
компьютера нужно снова запустить start (скрипт сам всё переподнимет).
"""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CLOUDFLARED = ROOT / "tools" / "bin" / "cloudflared.exe"
PID_DIR = ROOT / "data"
SERVER_PID = PID_DIR / "miniapp_server.pid"
TUNNEL_PID = PID_DIR / "tunnel.pid"
SERVER_LOG = PID_DIR / "miniapp.log"
TUNNEL_LOG = PID_DIR / "tunnel.log"
PORT = 8000

if os.name == "nt":
    DETACHED = 0x00000008 | 0x00000200
else:
    DETACHED = 0


def _pid_alive(pid: int) -> bool:
    try:
        out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"], capture_output=True, text=True)
        return str(pid) in out.stdout
    except Exception:
        return False


def _read_pid(path: Path) -> int:
    try:
        return int(path.read_text().strip())
    except (ValueError, OSError):
        return 0


def _kill(pid: int) -> None:
    if pid and _pid_alive(pid):
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)


def _spawn(cmd, log: Path, cwd: Path) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    handle = open(log, "a", encoding="utf-8", errors="replace")
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=DETACHED,
        env=env,
    )
    return proc.pid


def _tunnel_url(timeout: float = 45.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if TUNNEL_LOG.exists():
            raw = TUNNEL_LOG.read_bytes()
            text = ""
            for enc in ("utf-16-le", "utf-8", "cp1251"):
                try:
                    text = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            found = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", text)
            if found:
                return found[-1]
        time.sleep(1.5)
    return ""


def set_env_value(key: str, value: str) -> None:
    path = ROOT / ".env"
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    out = []
    replaced = False
    for line in lines:
        if line.strip().startswith(key + "="):
            out.append("%s=%s" % (key, value))
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append("%s=%s" % (key, value))
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out) + "\n")


def publish_config(url: str) -> None:
    """Публикует адрес API в miniapp/config.json и отправляет в GitHub.

    Приложение на GitHub Pages берёт адрес API оттуда — так его не нужно
    передеплоивать при смене туннеля.
    """
    config_path = ROOT / "miniapp" / "config.json"
    payload = {
        "api_base": url,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    with io.open(config_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, indent=1) + "\n")

    git = r"C:\Program Files\Git\cmd\git.exe"
    if not Path(git).exists():
        print("config.json обновлён (git не найден — Pages подхватит при следующем пуше)")
        return
    try:
        subprocess.run([git, "add", "miniapp/config.json"], cwd=str(ROOT), capture_output=True)
        commit = subprocess.run(
            [git, "commit", "-m", "chore: adres API dlya Mini App"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        if "nothing to commit" in (commit.stdout or "") + (commit.stderr or ""):
            print("config.json без изменений")
            return
        push = subprocess.run(
            [git, "push", "origin", "main"], cwd=str(ROOT), capture_output=True, text=True
        )
        if push.returncode == 0:
            print("config.json отправлен в GitHub — Pages обновится за минуту")
        else:
            print("config.json обновлён локально, но пуш не прошёл (нужна авторизация Git)")
    except Exception as exc:
        print("не удалось отправить config.json: %s" % exc)


def start() -> int:
    if not CLOUDFLARED.exists():
        print("Не найден cloudflared:", CLOUDFLARED)
        print("Скачай: https://github.com/cloudflare/cloudflared/releases/latest")
        return 1

    # 1. сервер
    server_pid = _read_pid(SERVER_PID)
    if server_pid and _pid_alive(server_pid):
        print("Сервер уже работает (PID %d)" % server_pid)
    else:
        pid = _spawn(
            [sys.executable, str(ROOT / "app" / "miniapp_server.py"), "--port", str(PORT)],
            SERVER_LOG,
            ROOT,
        )
        SERVER_PID.write_text(str(pid))
        print("Сервер Mini App запущен (PID %d), порт %d" % (pid, PORT))
        time.sleep(4)

    # 2. туннель
    tunnel_pid = _read_pid(TUNNEL_PID)
    if tunnel_pid and _pid_alive(tunnel_pid):
        print("Туннель уже работает (PID %d)" % tunnel_pid)
    else:
        # Лог обрезаем: иначе подхватится адрес от прошлого туннеля
        TUNNEL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with io.open(TUNNEL_LOG, "w", encoding="utf-8"):
            pass
        pid = _spawn(
            [str(CLOUDFLARED), "tunnel", "--url", "http://127.0.0.1:%d" % PORT, "--no-autoupdate"],
            TUNNEL_LOG,
            ROOT,
        )
        TUNNEL_PID.write_text(str(pid))
        print("Туннель запущен (PID %d), жду адрес..." % pid)

    url = _tunnel_url()
    if not url:
        print("Не удалось получить публичный адрес. Смотри %s" % TUNNEL_LOG)
        return 1

    # Проверяем, что адрес реально отвечает
    try:
        import httpx

        for _ in range(8):
            try:
                probe = httpx.get(url + "/health", timeout=20)
                if probe.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(4)
    except Exception:
        pass

    # 3. адрес в .env + перезапуск бота
    set_env_value("WEBAPP_BASE_URL", url)
    print("WEBAPP_BASE_URL = %s" % url)

    # Если приложение живёт на GitHub Pages — публикуем адрес API туда же
    pages_url = os.environ.get("PAGES_URL", "").strip()
    if pages_url:
        publish_config(url)
        set_env_value("WEBAPP_BASE_URL", pages_url)
        print("Кнопка в боте -> %s (постоянный адрес Pages)" % pages_url)

    subprocess.run(
        [sys.executable, str(ROOT / "tools" / "botctl.py"), "restart"],
        cwd=str(ROOT),
        capture_output=True,
    )
    print("Бот перезапущен — кнопка «Открыть приложение» уже в меню.")
    print("")
    print("Проверить: %s/health" % url)
    return 0


def stop() -> int:
    for path in (SERVER_PID, TUNNEL_PID):
        _kill(_read_pid(path))
        path.unlink(missing_ok=True)
    print("Остановлено")
    return 0


def status() -> int:
    server_pid = _read_pid(SERVER_PID)
    tunnel_pid = _read_pid(TUNNEL_PID)
    print("сервер:  %s" % ("работает (PID %d)" % server_pid if _pid_alive(server_pid) else "не работает"))
    print("туннель: %s" % ("работает (PID %d)" % tunnel_pid if _pid_alive(tunnel_pid) else "не работает"))
    return 0


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    if action == "start":
        sys.exit(start())
    if action == "stop":
        sys.exit(stop())
    sys.exit(status())
