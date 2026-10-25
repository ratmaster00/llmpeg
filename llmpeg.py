#!/usr/bin/env python3
"""llmpeg - describe what you want done to a media file; Gemini writes the ffmpeg command.

pip install google-genai rich
usage: llmpeg.py video.mkv "make a 720p mp4 under 20MB for discord"
Config: ~/.config/llmpeg.conf (created on first run)
"""
import argparse, json, os, shlex, subprocess, sys, time

from google import genai
from google.genai import types
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.syntax import Syntax
from rich.table import Table

CONF = os.path.expanduser("~/.config/llmpeg.conf")
DEFAULT_MODEL = "gemini-3.1-flash-lite"
TEMPLATE = f"""# llmpeg config (free key: https://aistudio.google.com/apikey)
api_key =
model = {DEFAULT_MODEL}
"""
MODEL = DEFAULT_MODEL
console = Console()

SYSTEM = """You turn requests into a single ffmpeg command.
Input: a trimmed ffprobe summary of the file, plus the user's request.
Reply with JSON only: {"args": ["ffmpeg", ...], "explanation": "one or two sentences"}.
Rules:
- args is an argv list: no shell syntax, no quoting, no pipes.
- Use the exact input path given. Never overwrite it.
- Write to ONE new output file (last argument), in the same directory unless told otherwise.
- Never use -y.
- Prefer stream copy (-c copy) when re-encoding isn't needed.
- For size targets, compute bitrate from the duration (leave room for audio)."""


def ensure_conf():
    """Create the config file (mode 600) if missing. Returns True if created."""
    if os.path.exists(CONF):
        return False
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    fd = os.open(CONF, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(TEMPLATE)
    return True


def load_conf():
    conf = {}
    with open(CONF) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                conf[k.strip().lower()] = v.strip().strip("\"'")
    return conf


def probe(path):
    raw = json.loads(subprocess.check_output(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_streams", path]))
    keep = ("index", "codec_type", "codec_name", "width", "height",
            "r_frame_rate", "channels", "sample_rate", "bit_rate")
    streams = []
    for s in raw.get("streams", []):
        d = {k: s[k] for k in keep if k in s}
        if lang := s.get("tags", {}).get("language"):
            d["language"] = lang
        streams.append(d)
    f = raw.get("format", {})
    fmt = {k: f[k] for k in ("format_name", "duration", "size", "bit_rate") if k in f}
    return {"format": fmt, "streams": streams}


def show_probe(info):
    t = Table(title="probe", header_style="bold cyan", border_style="dim")
    for col in ("#", "type", "codec", "details"):
        t.add_column(col)
    for s in info["streams"]:
        if s["codec_type"] == "video":
            det = f"{s.get('width')}x{s.get('height')} @ {s.get('r_frame_rate')}"
        elif s["codec_type"] == "audio":
            det = f"{s.get('channels')}ch {s.get('sample_rate')}Hz {s.get('language', '')}"
        else:
            det = s.get("language", "")
        t.add_row(str(s["index"]), s["codec_type"], s.get("codec_name", "?"), det)
    f = info["format"]
    mb = int(f.get("size", 0)) / 1e6
    t.caption = f"{f.get('format_name')} | {float(f.get('duration', 0)):.1f}s | {mb:.1f} MB"
    console.print(t)


def ask(client, prompt, verbose=False):
    if verbose:
        console.print(Panel(prompt, title=f"prompt -> {MODEL}", border_style="dim"))
    with console.status("[cyan]Asking Gemini...", spinner="dots"):
        for i in range(4):
            try:
                resp = client.models.generate_content(
                    model=MODEL, contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM, response_mime_type="application/json"))
                break
            except genai.errors.ServerError as e:
                if i == 3:
                    sys.exit(f"Gemini is overloaded: {e.code} {e.status}")
                console.print(f"[yellow]{e.code}, retrying in {2 ** (i + 1)}s...")
                time.sleep(2 ** (i + 1))
    if verbose:
        console.print(Panel(resp.text, title="raw response", border_style="dim"))
    return json.loads(resp.text)


def check(args, src):
    """Return an error string if the command looks unsafe, else None."""
    if not args or args[0] != "ffmpeg":
        return "command doesn't start with ffmpeg"
    out = args[-1]
    if src and os.path.abspath(out) == os.path.abspath(src):
        return "output is the input file"
    if os.path.exists(out):
        return f"output already exists: {out}"
    return None


def run(args, live):
    """Run ffmpeg, capture stderr (optionally echoing it live). Returns (rc, stderr)."""
    p = subprocess.Popen(args, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    buf = ""
    for ch in iter(lambda: p.stderr.read(1), ""):
        buf += ch
        if live:
            sys.stderr.write(ch)
            sys.stderr.flush()
    return p.wait(), buf


def main():
    global MODEL
    ap = argparse.ArgumentParser(description="plain-English ffmpeg")
    ap.add_argument("args", nargs="+", metavar="[file] request")
    ap.add_argument("--nofile", action="store_true", help="no input file (generate from scratch)")
    ap.add_argument("-y", "--yes", action="store_true", help="skip confirmation")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="show prompt, raw response, live ffmpeg output")
    a = ap.parse_args()
    if a.nofile:
        src, request = None, " ".join(a.args)
    elif len(a.args) < 2:
        ap.error("need a file and a request (or use --nofile)")
    else:
        src, request = a.args[0], " ".join(a.args[1:])

    if ensure_conf():
        console.print(f"[yellow]Created {CONF}[/yellow]")
    conf = load_conf()
    MODEL = os.environ.get("LLMPEG_MODEL") or conf.get("model") or DEFAULT_MODEL
    key = os.environ.get("GEMINI_API_KEY") or conf.get("api_key")
    if not key:
        sys.exit(f"No API key. Set api_key in {CONF} (free key: https://aistudio.google.com/apikey)")
    client = genai.Client(api_key=key)

    if src:
        info = probe(src)
        show_probe(info)
        prompt = f"File: {src}\nProbe: {json.dumps(info)}\nRequest: {request}"
    else:
        prompt = f"No input file; generate from scratch (e.g. lavfi sources).\nRequest: {request}"

    while True:
        plan = ask(client, prompt, a.verbose)
        args = [x for x in plan["args"] if x != "-y"]
        if err := check(args, src):
            console.print(f"[red]Refusing: {err}")
            sys.exit(1)
        if "-n" not in args:
            args.insert(1, "-n")

        console.print(Panel(plan["explanation"], title="[bold green]plan", border_style="green"))
        console.print(Syntax(shlex.join(args), "bash", word_wrap=True))

        if not a.yes and not Confirm.ask("[yellow]Run?", default=False):
            return
        if a.verbose:
            rc, err = run(args, live=True)
        else:
            with console.status("[cyan]Running ffmpeg...", spinner="dots"):
                rc, err = run(args, live=False)
        if rc == 0:
            console.print(f"[green]✓ done -> {args[-1]}")
            return

        tail = err[-1500:]
        console.print(Panel(tail, title="[red]ffmpeg error", border_style="red"))
        if os.path.exists(args[-1]):
            os.remove(args[-1])  # partial output from the failed run
        if Confirm.ask("[yellow]Ask Gemini to fix it?", default=True):
            prompt += (f"\n\nYour previous command was: {shlex.join(args)}\n"
                       f"It failed with:\n{tail}\nReturn a corrected command.")
        else:
            sys.exit(rc)


if __name__ == "__main__":
    main()
