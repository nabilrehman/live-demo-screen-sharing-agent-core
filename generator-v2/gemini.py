"""Small Gemini REST helper (key from ~/Downloads/livekit-ops/gemini_key, never printed)."""
import base64, json, os, time, urllib.error, urllib.request

KEY_PATH = os.path.expanduser(os.getenv("GEMINI_KEY_FILE", "~/Downloads/livekit-ops/gemini_key"))
TEXT_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemini-3.1-pro-preview")
URL = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"


def key():
    return os.getenv("GEMINI_API_KEY") or open(KEY_PATH).read().strip()


def generate(parts, model=TEXT_MODEL, json_out=False, timeout=600):
    body = {"contents": [{"parts": parts}]}
    if json_out:
        body["generationConfig"] = {"responseMimeType": "application/json"}
    for attempt in range(4):
        req = urllib.request.Request(URL.format(m=model), data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "x-goog-api-key": key()})
        try:
            r = json.load(urllib.request.urlopen(req, timeout=timeout))
            txt = "".join(p.get("text", "") for p in r["candidates"][0]["content"]["parts"])
            return json.loads(txt) if json_out else txt
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 503) and attempt < 3:
                time.sleep(10 * (attempt + 1)); continue
            raise RuntimeError(f"Gemini {e.code}: {e.read()[:300]}")


def image_part(path, max_bytes=6_000_000):
    """PNG screenshots can be huge (full page); shrink to a JPEG under max_bytes."""
    from PIL import Image
    import io
    im = Image.open(path).convert("RGB")
    if im.height > 6000:
        im = im.crop((0, 0, im.width, 6000))
    if im.width > 1440:
        im = im.resize((1440, round(im.height * 1440 / im.width)))
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=70)
    return {"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}}
