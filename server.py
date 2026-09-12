#!/usr/bin/env python3
"""Local web UI for book_editions.

    python server.py            ->  http://localhost:8000

A backend is not a preference here, it is forced: SBN sends no
Access-Control-Allow-Origin header of any kind, so a browser cannot call it
directly from a static page. Serving the UI and a JSON facade from one origin
sidesteps CORS entirely, and keeps the Google Books key server-side.

Stdlib only, plus requests (already the project's single dependency).
"""

import errno
import json
import mimetypes
import os
import posixpath
import sys
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from lookup import googlebooks, langs, sbn
from lookup.net import SourceError
from lookup.pipeline import lookup

WEB_ROOT = Path(__file__).parent / "web"
PORT = int(os.environ.get("PORT", 8000))


class Handler(BaseHTTPRequestHandler):
    server_version = "book-editions/3.0"
    protocol_version = "HTTP/1.1"

    # -- helpers ----------------------------------------------------------
    def _send(self, status, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def log_message(self, fmt, *args):
        sys.stderr.write(f"  {self.address_string()} {fmt % args}\n")

    # -- routing ----------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)

        try:
            if route == "/api/lookup":
                return self._api_lookup(query)
            if route == "/api/sbn/record":
                return self._api_record(query)
            if route == "/api/health":
                return self._api_health()
            if route.startswith("/api/"):
                return self._json({"error": f"no such endpoint: {route}"}, 404)
            return self._static(parsed.path)
        except BrokenPipeError:
            pass
        except Exception as exc:                      # never take the server down
            self.log_message("unhandled: %r", exc)
            self._json({"error": str(exc)}, 500)

    do_HEAD = do_GET

    def _one(self, query, key):
        value = (query.get(key) or [""])[0].strip()
        return value or None

    def _api_lookup(self, query):
        title = self._one(query, "title")
        author = self._one(query, "author")
        if not title and not author:
            return self._json({"error": "give a title or an author"}, 400)

        report = lookup(
            title, author,
            year_from=self._one(query, "year_from"),
            year_to=self._one(query, "year_to"),
            publisher=self._one(query, "publisher"),
        )
        payload = report.to_dict()
        # The UI needs display names for language codes it has never seen.
        # Iterate the serialised payload, not the dataclass: Edition objects
        # have no .get(), and the rows here are already plain dicts.
        mentioned = set(payload["editions_by_language"])
        for group in payload["editions_by_language"].values():
            for edition in group:
                mentioned.update(edition.get("available_languages") or [])
        if report.cluster.original_language:
            mentioned.add(report.cluster.original_language)
        payload["language_names"] = {code: langs.display(code) for code in mentioned}

        # Echo any active filter back, so a short result list explains itself.
        bits = []
        if self._one(query, "year_from") or self._one(query, "year_to"):
            bits.append(f"{self._one(query, 'year_from') or 'any'}"
                        f"\u2013{self._one(query, 'year_to') or 'any'}")
        if self._one(query, "publisher"):
            bits.append(self._one(query, "publisher"))
        payload["filters_applied"] = ", ".join(bits) or None
        return self._json(payload)

    def _api_record(self, query):
        bid = self._one(query, "bid")
        if not bid:
            return self._json({"error": "bid required"}, 400)
        try:
            edition = sbn.to_edition(sbn.full_record(bid))
        except SourceError as exc:
            return self._json({"error": str(exc)}, 502)
        return self._json(asdict(edition))

    def _api_health(self):
        return self._json({
            "ok": True,
            "google_books": "configured" if googlebooks.available() else "no API key",
            "sources": ["Wikidata", "Open Library", "SBN"]
                       + (["Google Books"] if googlebooks.available() else []),
        })

    def _static(self, path):
        rel = posixpath.normpath(unquote(path)).lstrip("/")
        if rel in ("", "."):
            rel = "index.html"
        target = (WEB_ROOT / rel).resolve()
        if not str(target).startswith(str(WEB_ROOT.resolve())) or not target.is_file():
            return self._send(404, b"not found", "text/plain; charset=utf-8")
        ctype, _ = mimetypes.guess_type(str(target))
        return self._send(200, target.read_bytes(), ctype or "application/octet-stream")


def main():
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        # Worth saying plainly: an already-running instance keeps serving its own
        # imported modules, so a stale one silently ignores edited code.
        print(f"Port {PORT} is already in use — another instance is probably still "
              f"running (it will be serving the code it started with).", file=sys.stderr)
        print(f"  find it:  lsof -nP -iTCP:{PORT} -sTCP:LISTEN", file=sys.stderr)
        print(f"  stop it:  pkill -f server.py", file=sys.stderr)
        print(f"  or pick another port:  PORT={PORT + 1} python server.py", file=sys.stderr)
        raise SystemExit(1)
    key = "set" if googlebooks.available() else "not set (source will be skipped)"
    print(f"book_editions UI  ->  http://localhost:{PORT}")
    print(f"GOOGLE_BOOKS_API_KEY: {key}")
    print("Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
        server.server_close()


if __name__ == "__main__":
    main()
