"""Finds where the Gemini call stalls. Prints timings and status codes only, never the key."""
import os, sys, time
import httpx

here = os.path.dirname(os.path.abspath(__file__))
key = ""
for p in (os.path.join(here, "..", "backend", ".env"), ".env"):
    if os.path.exists(p):
        for line in open(p, encoding="utf-8-sig"):
            if line.startswith("GEMINI_API_KEY="):
                key = line.split("=", 1)[1].strip().strip("\"'")
        break
print("key found:", bool(key), "| length:", len(key), "| prefix:", key[:3])
base = "https://generativelanguage.googleapis.com/v1beta/models"
body = {"contents": [{"parts": [{"text": "say ok"}]}]}

def run(label, fn):
    t = time.time()
    try:
        r = fn()
        print(f"[{label}] {r.status_code} in {time.time()-t:.1f}s  {r.text[:120].replace(chr(10),' ')}")
    except Exception as e:
        print(f"[{label}] FAILED after {time.time()-t:.1f}s: {type(e).__name__}")

run("1 no key (expect 403)", lambda: httpx.get(base, timeout=20))
run("2 list models with key", lambda: httpx.get(base, headers={"x-goog-api-key": key}, timeout=20))
r = httpx.get(base + "?pageSize=100", headers={"x-goog-api-key": key}, timeout=20)
names = [m["name"].split("/")[1] for m in r.json().get("models", [])
         if "generateContent" in m.get("supportedGenerationMethods", [])]
cands = [n for n in names if "flash" in n and not any(x in n for x in ("image", "tts", "live", "audio", "embedding", "robotics", "computer"))]
print("usable flash models:", cands)
for m in cands[:8]:
    run(f"3 generate {m}", lambda m=m: httpx.post(f"{base}/{m}:generateContent",
        headers={"x-goog-api-key": key}, json=body, timeout=40))
print("env proxies:", {k: bool(os.environ.get(k)) for k in ("HTTP_PROXY","HTTPS_PROXY","ALL_PROXY")})
