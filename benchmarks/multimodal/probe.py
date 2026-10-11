# Mide extracción de una factura escaneada y transcripción de audio contra el perfil activo.
# Uso: probe.py <imagen> <repeticiones> [directorio con voice.toml y media/voice-<id>.wav ...]
# La factura sintética está en invoice-scan.jpg; su texto fuente, en invoice-scan.txt.
# El audio debe ser WAV mono de 16 kHz: los clips de menos de ~1,5 s se rechazan o se cortan.
import base64, json, re, sys, time, tomllib, unicodedata, urllib.request, pathlib
URL = "http://127.0.0.1:18080/v1/chat/completions"
def chat(content, max_tokens=1200):
    body = {"model": "x", "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens,
            "temperature": 0.2, "chat_template_kwargs": {"enable_thinking": False}}
    t = time.time()
    r = json.load(urllib.request.urlopen(urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type": "application/json"}), timeout=300))
    return r["choices"][0]["message"].get("content") or "", time.time() - t, r["usage"]
EXPECTED = {"ruc": "80012345-6", "numero": "001-002-0004587", "fecha": "2026-09-14", "paciente": "María Belén Ortiz Giménez",
            "ci": "4512887", "total": 1220000, "iva": 110909,
            "items": [("consulta", 1, 150000, 150000), ("limpieza", 1, 250000, 250000), ("resina", 2, 320000, 640000), ("radiograf", 3, 60000, 180000)]}
PROMPT = ("Extraé los datos de esta factura escaneada y devolvé SOLO un JSON con esta forma: "
          '{"ruc": str, "numero": str, "fecha": "YYYY-MM-DD", "paciente": str, "ci": str (solo dígitos), '
          '"items": [{"detalle": str, "cantidad": int, "precio_unitario": int, "total": int}], "iva": int, "total": int}. '
          "Los montos son guaraníes: el punto es separador de miles, devolvé enteros.")
def score(data):
    ok = total = 0
    for k in ("ruc", "numero", "fecha", "paciente", "ci", "total", "iva"):
        total += 1; ok += str(data.get(k, "")).strip() == str(EXPECTED[k])
    items = data.get("items") or []
    for i, (word, qty, unit, tot) in enumerate(EXPECTED["items"]):
        it = items[i] if i < len(items) else {}
        total += 4
        ok += word in str(it.get("detalle", "")).lower()
        ok += it.get("cantidad") == qty; ok += it.get("precio_unitario") == unit; ok += it.get("total") == tot
    return ok, total
def norm(s):
    s = unicodedata.normalize("NFKD", s.lower()); s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9ñ ]+", " ", s).split()
def wer(ref, hyp):
    r, h = norm(ref), norm(hyp); d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
    return d[len(h)] / max(1, len(r)), len(r)
if len(sys.argv) < 3: sys.exit(__doc__ or "Uso: probe.py <imagen> <repeticiones> [directorios de audio...]")
image, runs = sys.argv[1], int(sys.argv[2])
img = base64.b64encode(open(image, "rb").read()).decode()
scores = []
for i in range(runs):
    text, dt, usage = chat([{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}}, {"type": "text", "text": PROMPT}])
    m = re.search(r"\{.*\}", text, re.S)
    try: data = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError: data = {}
    ok, total = score(data); scores.append(ok / total)
    print(f"imagen {i}: {ok}/{total} campos  {dt:.1f}s  prompt={usage['prompt_tokens']} out={usage['completion_tokens']}")
    if i == 0: print("   ", json.dumps(data, ensure_ascii=False)[:600])
print(f"IMAGEN media {sum(scores)/len(scores):.0%}")
errs = words = 0; secs = 0.0
for vdir in sys.argv[3:]:
    lines = tomllib.loads(open(pathlib.Path(vdir) / "voice.toml", "rb").read().decode())["line"]
    for line in lines:
        wav = pathlib.Path(vdir) / "media" / f"voice-{line['id']}.wav"
        if not wav.exists(): continue
        b = base64.b64encode(wav.read_bytes()).decode()
        text, dt, _ = chat([{"type": "input_audio", "input_audio": {"data": b, "format": "wav"}},
                            {"type": "text", "text": "Transcribí este audio en español, literal. Devolvé solo la transcripción."}], 300)
        w, n = wer(line["text"], text); errs += w * n; words += n; secs += dt
        if w > 0.15: print(f"  audio {line['id']}: WER {w:.0%} | ref: {line['text'][:80]} | hyp: {text.strip()[:80]}")
if words: print(f"AUDIO WER {errs/words:.1%} sobre {words} palabras, {secs:.1f}s en total")
