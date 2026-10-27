"""
Spotify -> synced lyrics -> ESP32-S2 TFT Feather (over USB serial)   v8 font mode

Font mode: sends the lyrics as text. The board draws them with its own
fonts (spotify_lyrics_font.ino), which include Traditional AND Simplified
Chinese plus English.

Messages sent to the board:
    T,song - artist     title
    M,current line      lyric
    C,                  clear the screen

Board sketch: spotify_lyrics_font/spotify_lyrics_font.ino

Install:  pip3 install spotipy requests pyserial
Run:      python3 spotify_lyrics_font.py

Lyrics come from LRCLIB (lrclib.net), a free community database,
so some songs won't have synced lyrics.
"""

import os
import queue
import re
import threading
import time
import unicodedata

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

    commands = queue.Queue()
    threading.Thread(target=read_keyboard, args=(commands,), daemon=True).start()
    print(HELP)

    port = SERIAL_PORT or find_port()
    print("Connecting to", port)
    board = serial.Serial(port, 115200, timeout=1)
    time.sleep(2)

    def send(kind, text=""):
        """Send one text message, e.g. send("M", "hello") -> 'M,hello\\n'.
        The board draws the text with its own Chinese + English fonts."""
        if kind == "B":
            return                       # next line isn't shown
        text = unicodedata.normalize("NFC", text).replace("\n", " ").strip()[:250]
        data = f"{kind},{text}\n".encode("utf-8")
        board.write(data)
        board.flush()
        time.sleep(0.08)                 # give the board time to draw

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

                # Time bar: tell the board where we are in the song.
                # (Add the time spent since we asked Spotify, e.g. looking up lyrics.)
                elapsed_ms = (current.get("progress_ms") or 0)
                if playing:
                    elapsed_ms += int((time.monotonic() - now) * 1000)
                send("P", f'{elapsed_ms},{item["duration_ms"]},{1 if playing else 0}')
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
