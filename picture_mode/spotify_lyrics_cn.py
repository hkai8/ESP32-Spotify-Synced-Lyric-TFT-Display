"""
Spotify -> synced lyrics -> ESP32-S2 TFT Feather (over USB serial)   v7

Picture mode: this script draws each line of text with one of your Mac's
fonts (which have every Chinese character, Traditional AND Simplified, plus
English, Japanese, Korean...) into a small black-and-white picture, and sends
the picture to the board. The board has no fonts at all, so nothing can be missing.

Messages sent to the board (spotify_lyrics_display_cn.ino v7):
    C,                              clear the screen
    I,<y>,<height>,<color>,<hex>    a 240-pixel-wide picture drawn at row y

Board sketch: spotify_lyrics_display_cn/spotify_lyrics_display_cn.ino

Install:  pip3 install spotipy requests pyserial pillow
Run:      python3 spotify_lyrics_cn.py

Lyrics come from LRCLIB (lrclib.net), a free community database,
so some songs won't have synced lyrics.
"""

import os
import queue
import re
import threading
import time
import unicodedata

from PIL import Image, ImageDraw, ImageFont
import requests
import serial
import spotipy
from serial.tools import list_ports
from spotipy.oauth2 import SpotifyOAuth

# ---- From your Spotify developer dashboard (https://developer.spotify.com/dashboard) ----
# Set them as environment variables so they never end up in git:
#   export SPOTIPY_CLIENT_ID="..."
#   export SPOTIPY_CLIENT_SECRET="..."
CLIENT_ID = os.environ.get("SPOTIPY_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("SPOTIPY_CLIENT_SECRET", "")
REDIRECT_URI = os.environ.get("SPOTIPY_REDIRECT_URI", "http://127.0.0.1:8888/callback")

SERIAL_PORT = None      # None = auto-detect. Or set e.g. "/dev/cu.usbmodem01"
POLL_SECONDS = 4        # how often to ask Spotify where the song is
LEAD_SECONDS = 0.5      # show each line slightly early

# ---- Look of the screen ----
LYRIC_SIZES = [24, 20, 17, 14]   # lyric font sizes to try, biggest first
TITLE_SIZES = [14, 12]           # title font sizes to try
FONT_PATH = None                 # None = find a Chinese font on your computer automatically

# Fonts that include Traditional + Simplified Chinese (first one found is used)
FONT_CANDIDATES = [
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    # Windows
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msjh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    # Linux (sudo apt install fonts-noto-cjk)
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
]

SCREEN_W = 240
TITLE_Y, TITLE_H = 0, 20
LYRIC_Y, LYRIC_H = 20, 115


def rgb565(r, g, b):
    """Colors on this screen are 16 bits: 5 for red, 6 for green, 5 for blue."""
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


GREEN = rgb565(30, 215, 96)
WHITE = rgb565(255, 255, 255)

# Matches timestamps like [01:23.45]
TIMESTAMP = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")


# USB vendor IDs: Adafruit, Espressif (ESP32-S2/S3 native USB)
BOARD_VIDS = {0x239A, 0x303A}


def find_port():
    """Find the Feather's USB serial port (Mac, Linux or Windows)."""
    ports = list_ports.comports()
    for p in ports:
        if p.vid in BOARD_VIDS:
            return p.device
    for p in ports:
        if "usbmodem" in p.device or "ttyACM" in p.device:
            return p.device
    raise SystemExit("Couldn't find the board. Is it plugged in, and is Serial Monitor closed?")


def find_font_path():
    if FONT_PATH:
        return FONT_PATH
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    raise SystemExit("Couldn't find a Chinese font. Set FONT_PATH at the top of the script "
                     "to a .ttf/.ttc/.otf font file that has Chinese characters.")


_fonts = {}


def get_font(size):
    """Load the font at a size (cached so it's only loaded once)."""
    if size not in _fonts:
        _fonts[size] = ImageFont.truetype(find_font_path(), size)
    return _fonts[size]


# One "piece" for wrapping: an English word, a run of spaces, or one other
# character (each Chinese character is its own piece, so rows can break
# between any two of them).
TOKEN = re.compile(r"[A-Za-z0-9'’\-]+[.,!?;:]*|\s+|.")


# Punctuation that shouldn't be the first thing on a row
NO_ROW_START = set("，。、！？；：,.!?;:)）」』】》…")


def wrap(text, font, max_w):
    """Break text into rows that fit max_w pixels."""
    rows, row = [], ""
    for tok in TOKEN.findall(text):
        if not row and tok.isspace():
            continue
        if font.getlength(row + tok) <= max_w:
            row += tok
            continue
        if tok in NO_ROW_START and row.strip():
            row += tok          # keep punctuation like ， on the row before it
            continue
        if row.strip():
            rows.append(row.rstrip())
        row = "" if tok.isspace() else tok
        while font.getlength(row) > max_w and len(row) > 1:   # word wider than the screen
            cut = len(row) - 1
            while cut > 1 and font.getlength(row[:cut]) > max_w:
                cut -= 1
            rows.append(row[:cut])
            row = row[cut:]
    if row.strip():
        rows.append(row.rstrip())
    return rows


def render(text, height, sizes):
    """Draw text centered in a 240 x height picture. Returns the raw bytes.

    Tries each font size (biggest first) until all rows fit.
    The bytes are 1 bit per pixel, 30 bytes per row, which is exactly the
    format the board's tft.drawBitmap() expects.
    """
    max_w = SCREEN_W - 8
    for size in sizes:
        font = get_font(size)
        ascent, descent = font.getmetrics()
        line_h = ascent + descent + 2
        rows = wrap(text, font, max_w)
        if len(rows) * line_h <= height:
            break

    max_rows = max(1, height // line_h)
    if len(rows) > max_rows:                     # still too long: end with …
        rows = rows[:max_rows]
        last = rows[-1]
        while last and font.getlength(last + "…") > max_w:
            last = last[:-1]
        rows[-1] = last.rstrip() + "…"

    img = Image.new("1", (SCREEN_W, height), 0)
    draw = ImageDraw.Draw(img)
    draw.fontmode = "1"                          # crisp pixels, no blurry edges
    top = (height - len(rows) * line_h) // 2
    for i, row in enumerate(rows):
        x = (SCREEN_W - font.getlength(row)) / 2
        draw.text((x, top + i * line_h), row, font=font, fill=1)
    return img.tobytes()


def parse_lrc(lrc_text):
    """Turn LRC text into a sorted list of (seconds, line) pairs."""
    lines = []
    for raw in lrc_text.splitlines():
        stamps = TIMESTAMP.findall(raw)
        words = TIMESTAMP.sub("", raw).strip()
        for minutes, seconds in stamps:
            lines.append((int(minutes) * 60 + float(seconds), words))
    lines.sort(key=lambda pair: pair[0])
    return lines


LRCLIB_HEADERS = {"User-Agent": "esp32-lyrics-display/1.0"}


def lrclib(endpoint, params):
    """Call one LRCLIB endpoint. Returns the JSON reply, or None."""
    r = requests.get(f"https://lrclib.net/api/{endpoint}", params=params,
                     headers=LRCLIB_HEADERS, timeout=10)
    return r.json() if r.status_code == 200 else None


def same_name(a, b):
    """Loose comparison: ignores case, spaces and punctuation."""
    clean = lambda s: "".join(ch for ch in (s or "").lower() if ch.isalnum())
    a, b = clean(a), clean(b)
    return bool(a) and bool(b) and (a in b or b in a)


def simple_title(title):
    """Remove extras that Spotify adds but LRCLIB often doesn't:
    "Song (Live)" / "Song - Remastered 2011" / "Song (feat. X)" / "Song【電視劇插曲】" -> "Song" """
    title = title or ""
    title = re.split(r"\s+-\s+", title)[0]
    title = re.sub(r"[\(\[（【《「].*?[\)\]）】》」]", "", title)
    return title.strip() or (title or "")


def get_lyrics(track):
    """Ask LRCLIB for synced lyrics that really belong to this song.

    Returns a list of (seconds, line), or None if no good match is found.
    It's better to show "no lyrics" than another song's lyrics, so search
    results are only accepted if their length is within a few seconds of the
    Spotify track (different versions/songs almost always differ more).
    """
    name = track["name"]
    short = simple_title(name)
    artists = [a["name"] for a in track["artists"]]
    duration = track["duration_ms"] / 1000

    def report(result, how):
        print(f'  lyrics: {result.get("trackName")} - {result.get("artistName")} '
              f'({result.get("duration")}s, found by {how})')
        return parse_lrc(result["syncedLyrics"])

    def good_match(result):
        """Chinese songs are often listed differently on Spotify and LRCLIB
        (e.g. the artist's English name on one, Chinese name on the other),
        so names alone aren't reliable. The song LENGTH is the best check:
          - within 2s and the title OR the artist matches -> accept
          - within 5s and the title AND the artist match  -> accept"""
        diff = abs((result.get("duration") or 0) - duration)
        title_ok = same_name(short, simple_title(result.get("trackName")))
        artist_ok = any(same_name(a, result.get("artistName")) for a in artists)
        return (diff <= 2 and (title_ok or artist_ok)) or (diff <= 5 and title_ok and artist_ok)

    seen = set()
    try:
        # 1) Exact lookups. LRCLIB itself checks the length (+/- 2s).
        for params in ({"album_name": track["album"]["name"]}, {}):
            result = lrclib("get", {"track_name": name, "artist_name": artists[0],
                                    "duration": round(duration), **params})
            if result and result.get("syncedLyrics"):
                return report(result, "exact match")

        # 2) Searches, from most to least specific
        searches = [{"track_name": name, "artist_name": artists[0]},
                    {"track_name": short, "artist_name": artists[0]},
                    {"q": f"{short} {artists[0]}"},
                    {"track_name": short},
                    {"q": short}]
        for params in searches:
            for result in lrclib("search", params) or []:
                if result.get("id") in seen or not result.get("syncedLyrics"):
                    continue
                seen.add(result.get("id"))
                if good_match(result):
                    return report(result, "search")
    except requests.RequestException as e:
        print("Lyrics lookup failed:", e)

    print(f"  lyrics: no good match found (checked {len(seen)} candidates)")
    return None


HELP = """
Commands (type one and press Enter):
  n   next song
  p   previous song
  r   restart this song
  b   back 10 seconds
  f   forward 10 seconds
  s   pause / play
  +   lyrics are late: show them 0.5s earlier
  -   lyrics are early: show them 0.5s later
  q   quit
"""


def read_keyboard(commands):
    """Runs in the background, waiting for typed commands.

    input() stops and waits until you press Enter. If the main loop did that,
    the lyrics would freeze while it waited. So this runs in its own thread
    and puts each command in a queue for the main loop to pick up.
    """
    while True:
        try:
            line = input()
        except EOFError:
            return
        commands.put(line.strip().lower())


def run_command(sp, cmd, position, playing):
    """Send one typed command to Spotify. Returns True to quit."""
    try:
        if cmd == "n":
            sp.next_track()
            print("-> next song")
        elif cmd == "p":
            # Spotify's "previous" restarts the song if you're more than a few
            # seconds in, so press it twice to really go back a song.
            sp.previous_track()
            if position > 3:
                time.sleep(0.3)
                sp.previous_track()
            print("-> previous song")
        elif cmd == "r":
            sp.seek_track(0)
            print("-> restart")
        elif cmd == "b":
            sp.seek_track(int(max(0, position - 10) * 1000))
            print("-> back 10s")
        elif cmd == "f":
            sp.seek_track(int((position + 10) * 1000))
            print("-> forward 10s")
        elif cmd == "s":
            if playing:
                sp.pause_playback()
                print("-> pause")
            else:
                sp.start_playback()
                print("-> play")
        elif cmd == "q":
            return True
        elif cmd:
            print(f"Unknown command '{cmd}'")
            print(HELP)
    except spotipy.SpotifyException as e:
        print("Spotify couldn't do that:", e.msg)
        if e.http_status == 404:
            print("(Make sure Spotify is open and playing on some device.)")
        elif e.http_status == 403:
            print("(This needs Spotify Premium, or delete .spotify_token_cache and log in again.)")
    return False


def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        raise SystemExit("Set SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET first (see README).")

    sp = spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            redirect_uri=REDIRECT_URI,
            # "modify" lets the script skip/pause; the "read" ones see what's playing
            scope="user-read-currently-playing user-read-playback-state user-modify-playback-state",
            cache_path=".spotify_token_cache",
        )
    )

    print("Using font:", find_font_path())

    commands = queue.Queue()
    threading.Thread(target=read_keyboard, args=(commands,), daemon=True).start()
    print(HELP)

    port = SERIAL_PORT or find_port()
    print("Connecting to", port)
    board = serial.Serial(port, 115200, timeout=1)
    time.sleep(2)

    def write(data):
        # Send in pieces with short pauses so the board's receive buffer
        # never overflows (overflow = lost data)
        for i in range(0, len(data), 1024):
            board.write(data[i:i + 1024])
            board.flush()
            time.sleep(0.003)
        time.sleep(0.12)   # give the board time to draw before the next message

    def send_picture(y, height, text, color, sizes):
        text = unicodedata.normalize("NFC", text).replace("\n", " ").strip()
        pixels = render(text, height, sizes)
        write(f"I,{y},{height},{color},{pixels.hex()}\n".encode())

    def send(kind, text=""):
        """send("C") clears, send("T", ...) sets the title, send("M", ...) sets the lyric."""
        if kind == "C":
            write(b"C,\n")
        elif kind == "T":
            send_picture(TITLE_Y, TITLE_H, text, GREEN, TITLE_SIZES)
        elif kind == "M":
            send_picture(LYRIC_Y, LYRIC_H, text, WHITE, LYRIC_SIZES)
        # "B" (next line) isn't shown, so it's ignored

    track_id = None
    lyrics = None
    last_index = -2
    playing = False
    base_progress = 0.0   # where Spotify last said we were (seconds)
    base_time = 0.0       # when it said that
    last_poll = 0.0
    lead = LEAD_SECONDS   # timing offset, adjustable with + and -

    send("C")
    send("T", "Connected")
    send("M", "Play something on Spotify")

    while True:
        now = time.monotonic()

        # Handle anything typed in Terminal
        while not commands.empty():
            cmd = commands.get()
            if cmd in ("+", "-"):
                lead = lead + 0.5 if cmd == "+" else lead - 0.5
                last_index = -2            # redraw the line right away
                print(f"-> timing offset now {lead:+.1f}s")
                continue
            position = base_progress + (now - base_time if playing else 0)
            if run_command(sp, cmd, position, playing):
                send("C")
                send("T", "Script stopped")
                print("Bye!")
                return
            time.sleep(0.3)        # give Spotify a moment to change
            last_poll = 0          # then check right away instead of waiting 4s
            now = time.monotonic()

        # Every few seconds, ask Spotify what's playing and where we are
        if now - last_poll >= POLL_SECONDS:
            last_poll = now
            try:
                current = sp.current_user_playing_track()
            except Exception as e:
                print("Spotify error:", e)
                current = None

            if current and current.get("item") and current.get("currently_playing_type") == "track":
                item = current["item"]
                playing = current["is_playing"]
                base_progress = (current.get("progress_ms") or 0) / 1000
                base_time = now

                item_key = item.get("id") or item.get("uri")
                if item_key != track_id:
                    track_id = item_key
                    title = f'{item["name"]} - {item["artists"][0]["name"]}'
                    print("Now playing:", title)
                    send("C")
                    send("T", title)
                    lyrics = get_lyrics(item)
                    last_index = -2
                    if not lyrics:
                        send("M", "(no synced lyrics found)")
            else:
                if track_id is not None:
                    send("C")
                    send("T", "Nothing playing")
                track_id, lyrics, playing = None, None, False

        # Between polls, estimate the position and show the right line
        if lyrics:
            position = base_progress + (now - base_time if playing else 0) + lead
            index = -1
            for i, (t, _) in enumerate(lyrics):
                if t <= position:
                    index = i
                else:
                    break

            if index != last_index:
                last_index = index
                current_line = lyrics[index][1] if index >= 0 else ""
                next_line = lyrics[index + 1][1] if index + 1 < len(lyrics) else ""
                send("M", current_line or "...")
                send("B", next_line)

        time.sleep(0.1)


if __name__ == "__main__":
    main()
