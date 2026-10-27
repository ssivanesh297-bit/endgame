import json
import os
import sqlite3
import time
import uuid
from email import policy
from email.parser import BytesParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
DATABASE = Path(os.environ.get("KATHA_DATABASE", ROOT / "katha.sqlite3"))
UPLOADS = ROOT / "uploads"
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
PORT = int(os.environ.get("KATHA_PORT", "8000"))

SAMPLE_STORIES = [
    ("The quiet art of saving seed for the next monsoon", "Farming", "Tamil", "Lakshmi Ammal", "Kovilpatti, Tamil Nadu", 2, 1, "A family seed-keeping practice that protects native millet through the dry months, shared across three generations.", "https://images.unsplash.com/photo-1500382017468-9049fed747ef?auto=format&fit=crop&w=1200&q=85", "A season held in the palm of a hand", "Before the first rain, Lakshmi Ammal chooses the strongest heads of millet and leaves them to dry in the shade. The seeds are stored with neem leaves in a clay pot, ready for the next season."),
    ("A tank that remembers the rain", "Water", "Kannada", "Channappa Gowda", "Hulikere, Karnataka", 5, 1, "How a village stone bund slows runoff and lets the hillside drink again.", "https://images.unsplash.com/photo-1470770841072-f978cf4d019e?auto=format&fit=crop&w=900&q=85", "Water held close to home", "The old bund is repaired before the rains. Small stones are placed across the channels so water slows, settles, and sinks back into the hillside."),
    ("The leaf kept beside the kitchen door", "Healing", "Tamil", "Mariammal Paati", "Pudur, Tamil Nadu", 7, 1, "A careful guide to identifying karpooravalli and the ways it has been used at home.", "https://images.unsplash.com/photo-1518531933037-91b2f5f229cc?auto=format&fit=crop&w=900&q=85", "A familiar leaf, a remembered use", "Mariammal Paati shows how to recognize karpooravalli by its soft, scalloped leaves. She remembers it as a plant always grown within reach of the kitchen."),
    ("Songs for the first planting day", "Culture", "Telugu", "Venkataiah", "Gongal, Andhra Pradesh", 14, 0, "A work song whose verses mark the rhythm of planting and the return of the rains.", "https://images.unsplash.com/photo-1518621736915-f3b1c41bfd00?auto=format&fit=crop&w=900&q=85", "A rhythm shared in the fields", "The first planting day begins with a song. Its lines set an easy pace for the work, and each person adds a verse remembered from home."),
]

ALLOWED_CATEGORIES = {"Farming", "Water", "Healing", "Culture"}
ALLOWED_LANGUAGES = {"Tamil", "Kannada", "Telugu", "Malayalam", "Other"}
ALLOWED_MEDIA = {
    "image/jpeg": ("image", ".jpg"), "image/png": ("image", ".png"),
    "image/webp": ("image", ".webp"), "image/gif": ("image", ".gif"),
    "audio/mpeg": ("audio", ".mp3"), "audio/mp4": ("audio", ".m4a"),
    "audio/wav": ("audio", ".wav"), "audio/x-wav": ("audio", ".wav"),
    "audio/ogg": ("audio", ".ogg"), "audio/webm": ("audio", ".webm"),
    "audio/aac": ("audio", ".aac"), "video/mp4": ("video", ".mp4"),
    "video/webm": ("video", ".webm"), "video/quicktime": ("video", ".mov"),
}


def connect_database():
    connection = sqlite3.connect(DATABASE, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database():
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    UPLOADS.mkdir(parents=True, exist_ok=True)
    with connect_database() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS stories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL, category TEXT NOT NULL, language TEXT NOT NULL,
                person TEXT NOT NULL, place TEXT NOT NULL, created_at INTEGER NOT NULL,
                verified INTEGER NOT NULL DEFAULT 0, description TEXT NOT NULL,
                image TEXT NOT NULL, caption TEXT NOT NULL, excerpt TEXT NOT NULL,
                media_url TEXT, media_type TEXT
            )"""
        )
        if connection.execute("SELECT COUNT(*) FROM stories").fetchone()[0] == 0:
            now = int(time.time() * 1000)
            for sample in SAMPLE_STORIES:
                title, category, language, person, place, days, verified, description, image, caption, excerpt = sample
                connection.execute(
                    """INSERT INTO stories
                    (title, category, language, person, place, created_at, verified,
                     description, image, caption, excerpt)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (title, category, language, person, place, now - days * 86400000,
                     verified, description, image, caption, excerpt),
                )


def serialize_story(row):
    return {
        "id": row["id"], "title": row["title"], "category": row["category"],
        "language": row["language"], "person": row["person"], "place": row["place"],
        "createdAt": row["created_at"], "verified": bool(row["verified"]),
        "description": row["description"], "image": row["image"],
        "caption": row["caption"], "excerpt": row["excerpt"],
        "mediaUrl": row["media_url"], "mediaType": row["media_type"],
    }


class KathaHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/health":
            self.send_json(200, {"status": "ok"})
            return
        if path == "/api/stories":
            with connect_database() as connection:
                rows = connection.execute("SELECT * FROM stories ORDER BY created_at DESC, id DESC").fetchall()
            self.send_json(200, [serialize_story(row) for row in rows])
            return
        if path == "/uploads/":
            self.send_error(404)
            return
        if path.startswith("/api/"):
            self.send_json(404, {"error": "API route not found."})
            return
        super().do_GET()

    def do_POST(self):
        if urlsplit(self.path).path != "/api/stories":
            self.send_json(404, {"error": "API route not found."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(400, {"error": "Invalid request size."})
            return
        if length <= 0 or length > MAX_UPLOAD_BYTES:
            self.send_json(413, {"error": "Choose a file smaller than 12 MB."})
            return
        try:
            data, media_bytes, media_type = self.read_submission(length)
            self.send_json(201, self.create_story(data, media_bytes, media_type))
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json(400, {"error": str(error)})
        except sqlite3.Error:
            self.send_json(500, {"error": "The archive could not save this story."})

    def read_submission(self, length):
        body = self.rfile.read(length)
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("application/json"):
            return json.loads(body), None, None
        if not content_type.startswith("multipart/form-data"):
            raise ValueError("Submit the contribution using the archive form.")
        message = BytesParser(policy=policy.default).parsebytes(
            b"Content-Type: " + content_type.encode("ascii") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
        )
        fields, media_bytes, media_type = {}, None, None
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if name == "media" and part.get_filename():
                media_bytes = part.get_payload(decode=True)
                media_type = part.get_content_type().lower()
            elif name:
                payload = part.get_payload(decode=True) or b""
                fields[name] = payload.decode(part.get_content_charset() or "utf-8").strip()
        return fields, media_bytes, media_type

    def create_story(self, data, media_bytes, media_type):
        required = ("title", "category", "language", "person", "place", "description")
        if not isinstance(data, dict):
            raise ValueError("Contribution details are missing.")
        if any(not isinstance(data.get(key), str) or not data[key].strip() for key in required):
            raise ValueError("Please complete all required fields.")
        if data.get("consent") != "yes":
            raise ValueError("Confirm you have permission to share this knowledge.")
        if data["category"] not in ALLOWED_CATEGORIES or data["language"] not in ALLOWED_LANGUAGES:
            raise ValueError("Choose a valid category and language.")
        limits = {"title": 72, "person": 80, "place": 120, "description": 240}
        for key, limit in limits.items():
            data[key] = data[key].strip()
            if len(data[key]) > limit:
                raise ValueError(f"{key.title()} must be {limit} characters or fewer.")

        media_url, media_kind, saved_path = None, None, None
        image = "https://images.unsplash.com/photo-1470252649378-9c29740c9fa8?auto=format&fit=crop&w=900&q=85"
        if media_bytes:
            if len(media_bytes) > MAX_UPLOAD_BYTES:
                raise ValueError("Choose a file smaller than 12 MB.")
            if media_type not in ALLOWED_MEDIA:
                raise ValueError("Use a JPG, PNG, WebP, GIF, MP3, WAV, OGG, MP4, or WebM file.")
            media_kind, extension = ALLOWED_MEDIA[media_type]
            filename = f"{uuid.uuid4().hex}{extension}"
            saved_path = UPLOADS / filename
            saved_path.write_bytes(media_bytes)
            media_url = f"/uploads/{filename}"
            if media_kind == "image":
                image = media_url

        now = int(time.time() * 1000)
        try:
            with connect_database() as connection:
                cursor = connection.execute(
                    """INSERT INTO stories
                    (title, category, language, person, place, created_at, verified,
                     description, image, caption, excerpt, media_url, media_type)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)""",
                    (data["title"], data["category"], data["language"], data["person"],
                     data["place"], now, data["description"], image,
                     "A new story from the community", data["description"], media_url, media_kind),
                )
                row = connection.execute("SELECT * FROM stories WHERE id = ?", (cursor.lastrowid,)).fetchone()
            return serialize_story(row)
        except sqlite3.Error:
            if saved_path:
                saved_path.unlink(missing_ok=True)
            raise


if __name__ == "__main__":
    initialize_database()
    server = ThreadingHTTPServer(
        ("127.0.0.1", PORT),
        lambda *args, **kwargs: KathaHandler(*args, directory=str(ROOT), **kwargs),
    )
    print(f"Katha local archive: http://127.0.0.1:{PORT}")
    print(f"SQLite database: {DATABASE}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nKatha server stopped.")
    finally:
        server.server_close()