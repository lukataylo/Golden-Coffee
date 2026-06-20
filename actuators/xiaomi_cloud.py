"""Xiaomi cloud transport — drive MIoT devices through the Mi cloud (no LAN).

Used when the machine running actuators/run.py is NOT on the same network as the
devices — e.g. the Mijia lamp + diffuser live in mainland China and the comfort
autopilot runs elsewhere.

Auth is the tricky part: a mainland-China account captcha-blocks scripted
username/password logins from a foreign IP. So instead we log in ONCE via a QR
code (scanned in the Mi Home app), cache the resulting session (userId /
serviceToken / ssecurity) in .xiaomi_session.json, and sign every command with it.
The session lasts a long time; re-run `python -m actuators.xiaomi --login` if it
expires.

Devices are addressed by `did`; each property by siid/piid from the model's MIoT
spec (home.miot-spec.com). Config lives in .env (XIAOMI_LAMP_*, XIAOMI_DIFFUSER_*).

The signing/encryption below is the standard Mi cloud scheme (RC4 + HMAC).
Degrades gracefully (prints intent) when unconfigured / no session / unreachable.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

try:
    from Crypto.Cipher import ARC4
except ModuleNotFoundError:  # pycryptodomex packaging
    from Cryptodome.Cipher import ARC4

import requests

REGION = os.environ.get("XIAOMI_REGION", "cn")
SESSION_FILE = Path(os.environ.get(
    "XIAOMI_SESSION_FILE",
    str(Path(__file__).resolve().parents[1] / ".xiaomi_session.json"),
))

WARMTH_KELVIN = {"warm": 2700, "neutral": 4000, "cool": 6000}

# Cloud HTTP reliability: the cn server is slow from far away (e.g. a venue abroad
# driving home gear in China), so give each call more time and a couple of retries.
CLOUD_TIMEOUT = float(os.environ.get("XIAOMI_CLOUD_TIMEOUT", "15"))
CLOUD_RETRIES = int(os.environ.get("XIAOMI_CLOUD_RETRIES", "3"))

LAMP_DID = os.environ.get("XIAOMI_LAMP_DID", "")
LAMP_SIID = int(os.environ.get("XIAOMI_LAMP_SIID", "2"))
LAMP_PIID_ON = int(os.environ.get("XIAOMI_LAMP_PIID_ON", "1"))
LAMP_PIID_BRIGHT = int(os.environ.get("XIAOMI_LAMP_PIID_BRIGHT", "2"))
LAMP_PIID_CT = os.environ.get("XIAOMI_LAMP_PIID_CT", "")  # blank => no colour temp

DIFF_DID = os.environ.get("XIAOMI_DIFFUSER_DID", "")
DIFF_SIID = int(os.environ.get("XIAOMI_DIFFUSER_SIID", "2"))
DIFF_PIID_ON = int(os.environ.get("XIAOMI_DIFFUSER_PIID_ON", "1"))
DIFF_PIID_LEVEL = os.environ.get("XIAOMI_DIFFUSER_PIID_LEVEL", "")
DIFF_LEVEL_MAX = int(os.environ.get("XIAOMI_DIFFUSER_LEVEL_MAX", "3"))


# ---------------------------------------------------------------- signing -----
def _gen_nonce(millis: int) -> str:
    nonce_bytes = os.urandom(8) + int(millis / 60000).to_bytes(4, byteorder="big")
    return base64.b64encode(nonce_bytes).decode()


def _signed_nonce(ssecurity: str, nonce: str) -> str:
    h = hashlib.sha256(base64.b64decode(ssecurity) + base64.b64decode(nonce))
    return base64.b64encode(h.digest()).decode()


def _enc_signature(url: str, method: str, signed_nonce: str, params: dict) -> str:
    parts = [method.upper(), url.split("com")[1].replace("/app/", "/")]
    parts += [f"{k}={v}" for k, v in params.items()]
    parts.append(signed_nonce)
    return base64.b64encode(hashlib.sha1("&".join(parts).encode("utf-8")).digest()).decode()


def _rc4(password: str, payload: bytes) -> bytes:
    cipher = ARC4.new(base64.b64decode(password))
    cipher.encrypt(bytes(1024))  # discard first 1024 bytes of keystream
    return cipher.encrypt(payload)


def _enc_params(url, method, signed_nonce, nonce, params, ssecurity) -> dict:
    params["rc4_hash__"] = _enc_signature(url, method, signed_nonce, params)
    for k, v in params.items():
        params[k] = base64.b64encode(_rc4(signed_nonce, v.encode())).decode()
    params.update({
        "signature": _enc_signature(url, method, signed_nonce, params),
        "ssecurity": ssecurity,
        "_nonce": nonce,
    })
    return params


def _to_json(text: str) -> dict:
    return json.loads(text.replace("&&&START&&&", ""))


def _api_url(server: str) -> str:
    return "https://" + ("" if server == "cn" else server + ".") + "api.io.mi.com/app"


# --------------------------------------------------------------- session ------
class _Cloud:
    """A logged-in Mi cloud session that can issue signed, encrypted API calls."""

    def __init__(self, server: str, user_id, service_token: str, ssecurity: str):
        self.server = server
        self.user_id = user_id
        self.service_token = service_token
        self.ssecurity = ssecurity
        self.session = requests.session()

    def api(self, path: str, data: dict):
        url = _api_url(self.server) + path
        params = {"data": json.dumps(data)}
        headers = {
            "Accept-Encoding": "identity",
            "Content-Type": "application/x-www-form-urlencoded",
            "x-xiaomi-protocal-flag-cli": "PROTOCAL-HTTP2",
            "MIOT-ENCRYPT-ALGORITHM": "ENCRYPT-RC4",
        }
        cookies = {
            "userId": str(self.user_id),
            "yetAnotherServiceToken": str(self.service_token),
            "serviceToken": str(self.service_token),
            "locale": "en_GB",
            "timezone": "GMT+02:00",
            "is_daylight": "1",
            "dst_offset": "3600000",
            "channel": "MI_APP_STORE",
        }
        nonce = _gen_nonce(round(time.time() * 1000))
        signed = _signed_nonce(self.ssecurity, nonce)
        fields = _enc_params(url, "POST", signed, nonce, dict(params), self.ssecurity)
        # Retry transient network errors — the Mi cloud (esp. the cn server reached
        # from far away) intermittently times out; a single command shouldn't fail
        # the actuator over one slow round-trip.
        last_exc = None
        for attempt in range(CLOUD_RETRIES):
            try:
                resp = self.session.post(url, headers=headers, cookies=cookies,
                                         params=fields, timeout=CLOUD_TIMEOUT)
                if resp.status_code != 200:
                    raise RuntimeError(f"cloud HTTP {resp.status_code}")
                decoded = _rc4(_signed_nonce(self.ssecurity, fields["_nonce"]),
                               base64.b64decode(resp.text))
                return json.loads(decoded)
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                last_exc = exc
                if attempt < CLOUD_RETRIES - 1:
                    print(f"[xiaomi-cloud] {type(exc).__name__}, retry {attempt + 1}/{CLOUD_RETRIES - 1}…")
        raise RuntimeError(f"cloud unreachable after {CLOUD_RETRIES} tries: {last_exc}")

    def miot_set(self, did: str, props: list[dict]):
        params = [{"did": str(did), **p} for p in props]
        resp = self.api("/miotspec/prop/set", {"params": params})
        # The top-level code can be 0 ("accepted") while individual properties still
        # fail — most often -704042011, the device being offline. Treat those as real
        # failures so the actuator doesn't claim success on an unplugged device.
        if resp.get("code") not in (0, None):
            raise RuntimeError(f"cloud error {resp.get('code')}: {resp.get('message')}")
        bad = [r for r in (resp.get("result") or []) if r.get("code") not in (0, None)]
        if bad:
            codes = sorted({r.get("code") for r in bad})
            if -704042011 in codes:
                raise RuntimeError("device offline (not connected to Wi-Fi / powered off)")
            raise RuntimeError(f"device rejected the change (codes {codes})")
        return resp

    def get_homes(self):
        return self.api("/v2/homeroom/gethome",
                        {"fg": True, "fetch_share": True, "fetch_share_dev": True, "limit": 300, "app_ver": 7})

    def get_devices(self, home_id, owner_id):
        return self.api("/v2/home/home_device_list",
                        {"home_owner": owner_id, "home_id": home_id, "limit": 200,
                         "get_split_device": True, "support_smart_home": True})

    def list_devices(self) -> list[dict]:
        """Flatten all of the account's homes into one device list (name/did/model/…)."""
        out: list[dict] = []
        homes = (self.get_homes() or {}).get("result", {}).get("homelist", []) or []
        for home in homes:
            res = self.get_devices(home["id"], self.user_id) or {}
            out.extend(res.get("result", {}).get("device_info") or [])
        return out

    def get_beaconkey(self, did: str) -> str:
        """The BLE bind-key ("beaconkey") for a Bluetooth device — the token the BLE
        driver needs to log into the lamp. It's NOT in the device list (that carries
        the Wi-Fi/miIO token); it comes from this dedicated endpoint. Returns the raw
        hex string, or "" if the device has none (e.g. a pure Wi-Fi device)."""
        resp = self.api("/v2/device/blt_get_beaconkey", {"did": str(did), "pdid": 1})
        return ((resp or {}).get("result") or {}).get("beaconkey", "") or ""


def _save_session(server, user_id, service_token, ssecurity) -> None:
    SESSION_FILE.write_text(json.dumps({
        "server": server, "user_id": user_id,
        "service_token": service_token, "ssecurity": ssecurity,
    }))
    try:
        SESSION_FILE.chmod(0o600)  # contains a service token — keep it private
    except OSError:
        pass


def _session_json() -> str:
    """The cached session JSON, from the file or — for deploys with no writable FS
    (Railway/containers) — the XIAOMI_SESSION_JSON env var. Env wins if both exist."""
    env = os.environ.get("XIAOMI_SESSION_JSON", "").strip()
    if env:
        return env
    if SESSION_FILE.exists():
        return SESSION_FILE.read_text()
    return ""


def session_available() -> bool:
    return bool(_session_json())


def load_session() -> _Cloud | None:
    raw = _session_json()
    if not raw:
        return None
    try:
        d = json.loads(raw)
        return _Cloud(d["server"], d["user_id"], d["service_token"], d["ssecurity"])
    except Exception:
        return None


# --------------------------------------------------------------- QR login -----
def _present_qr(img: bytes, login_url: str) -> None:
    """Show the QR every way that avoids stale/cached codes: a fresh PNG opened in
    the OS image viewer, plus an in-terminal ASCII render as a fallback."""
    try:
        f = tempfile.NamedTemporaryFile(prefix="mi_qr_", suffix=".png", delete=False)
        f.write(img)
        f.close()
        if sys.platform == "darwin":
            subprocess.run(["open", f.name], check=False)
            print(f"  → A QR code image just opened in Preview (file: {f.name}).")
        else:
            print(f"  → QR code image saved at {f.name} — open it and scan in Mi Home.")
    except Exception:
        pass
    try:
        import qrcode

        qr = qrcode.QRCode(border=1)
        qr.add_data(login_url)
        qr.make(fit=True)
        print("  …or scan this directly from the terminal:\n")
        qr.print_ascii(invert=True)
    except Exception:
        print(f"  …or open this login URL on another device: {login_url}")
    print("\n  Scan it in your Mi Home app and approve on your phone.")


def login_qr(server: str | None = None) -> _Cloud | None:
    """Interactive QR-code login. Scan the code in the Mi Home app, approve, and
    the resulting session is cached to SESSION_FILE. Returns the live session.

    Each call mints a brand-new QR; the codes are single-use and expire in ~2 min,
    so scan promptly."""
    server = server or REGION
    s = requests.session()

    r = s.get("https://account.xiaomi.com/longPolling/loginUrl", params={
        "_qrsize": "480", "qs": "%3Fsid%3Dxiaomiio%26_json%3Dtrue",
        "callback": "https://sts.api.io.mi.com/sts", "_hasLogo": "false",
        "sid": "xiaomiio", "serviceParam": "", "_locale": "en_GB",
        "_dc": str(int(time.time() * 1000)),
    })
    rd = _to_json(r.text)
    if "qr" not in rd:
        print("[xiaomi-cloud] could not start QR login")
        return None
    qr_url, login_url, lp = rd["qr"], rd["loginUrl"], rd["lp"]

    _present_qr(s.get(qr_url).content, login_url)
    print("  Waiting for the scan…  (Ctrl-C to abort)")

    # Long-poll: Xiaomi holds each request open until you approve (or the QR dies).
    deadline = time.time() + 180
    while time.time() < deadline:
        try:
            resp = s.get(lp, timeout=60)
        except requests.exceptions.Timeout:
            continue
        except requests.exceptions.RequestException as exc:
            print(f"[xiaomi-cloud] long-poll error: {exc}")
            return None
        if resp.status_code != 200:
            continue
        rd = _to_json(resp.text)
        if "userId" in rd and rd.get("ssecurity"):
            break  # approved
        code = rd.get("code")
        # 0 = ok (handled above); anything else here means the QR expired/was rejected.
        if code not in (None, 0):
            print(f"[xiaomi-cloud] QR expired before it was scanned (code {code}). "
                  f"Re-run --login for a fresh code and scan within ~2 min.")
            return None
    else:
        print("[xiaomi-cloud] timed out waiting for the scan; re-run --login.")
        return None

    user_id, ssecurity, location = rd["userId"], rd["ssecurity"], rd["location"]
    tok = s.get(location, headers={"content-type": "application/x-www-form-urlencoded"})
    if tok.status_code != 200 or "serviceToken" not in tok.cookies:
        print("[xiaomi-cloud] failed to obtain service token after scan")
        return None
    service_token = tok.cookies["serviceToken"]
    _save_session(server, user_id, service_token, ssecurity)
    print(f"[xiaomi-cloud] logged in (session cached → {SESSION_FILE.name})")
    return _Cloud(server, user_id, service_token, ssecurity)


# --------------------------------------------------------------- control ------
def lamp_configured() -> bool:
    return bool(LAMP_DID and session_available())


def diffuser_configured() -> bool:
    return bool(DIFF_DID and session_available())


def _need_session() -> _Cloud | None:
    cloud = load_session()
    if cloud is None:
        print("[xiaomi-cloud] no session — run: python -m actuators.xiaomi --login")
    return cloud


def lamp_set(brightness: int, warmth: str = "neutral") -> bool:
    brightness = max(0, min(100, int(brightness)))
    if not LAMP_DID:
        print(f"[xiaomi-cloud] (lamp unconfigured) would set {brightness}% / {warmth}")
        return False
    cloud = _need_session()
    if cloud is None:
        return False
    try:
        if brightness <= 0:
            cloud.miot_set(LAMP_DID, [{"siid": LAMP_SIID, "piid": LAMP_PIID_ON, "value": False}])
            print("[xiaomi-cloud] lamp off")
            return True
        props = [
            {"siid": LAMP_SIID, "piid": LAMP_PIID_ON, "value": True},
            {"siid": LAMP_SIID, "piid": LAMP_PIID_BRIGHT, "value": brightness},
        ]
        if LAMP_PIID_CT:
            props.append({"siid": LAMP_SIID, "piid": int(LAMP_PIID_CT),
                          "value": WARMTH_KELVIN.get(warmth, 4000)})
        cloud.miot_set(LAMP_DID, props)
        print(f"[xiaomi-cloud] lamp brightness {brightness}% / {warmth}")
        return True
    except Exception as exc:
        print(f"[xiaomi-cloud] lamp failed: {exc}")
        return False


def diffuser_set(intensity: int, scent: str = "fresh") -> bool:
    intensity = max(0, min(100, int(intensity)))
    on = intensity > 0
    if not DIFF_DID:
        print(f"[xiaomi-cloud] (diffuser unconfigured) would set {intensity}% ({scent})")
        return False
    cloud = _need_session()
    if cloud is None:
        return False
    try:
        props = [{"siid": DIFF_SIID, "piid": DIFF_PIID_ON, "value": on}]
        if on and DIFF_PIID_LEVEL:
            level = max(1, min(DIFF_LEVEL_MAX, round(intensity / 100 * DIFF_LEVEL_MAX)))
            props.append({"siid": DIFF_SIID, "piid": int(DIFF_PIID_LEVEL), "value": level})
            cloud.miot_set(DIFF_DID, props)
            print(f"[xiaomi-cloud] diffuser on level {level}/{DIFF_LEVEL_MAX} ({scent})")
        else:
            cloud.miot_set(DIFF_DID, props)
            print(f"[xiaomi-cloud] diffuser {'on' if on else 'off'} ({scent})")
        return True
    except Exception as exc:
        print(f"[xiaomi-cloud] diffuser failed: {exc}")
        return False
