#!/usr/bin/env python3
"""The server: a job id at once, versioned snapshots after it.

    python server.py                 ->  http://localhost:8000
    python3 -m app.server            ->  the same, by its module name

    POST /lookup   {"title": ..., "author": ...,  ->  202 {"id": ..., "version": 0}
                    "variants": [...]?,              (other spellings, from author mode)
                    "title_spellings": bool?,        (the reader's switches, decision AV;
                    "author_spellings": bool?}        off when absent)
    GET  /lookup/<id>?v=<held>                    ->  200 a snapshot, or
                                                      200 {"unchanged": true, ...}
                                                      404 the job is gone
    GET  /lookup/<id>/edition/<edition id>        ->  200 one row, in full
    POST /lookup/<id>/add  {"keys": [...]}        ->  200 what was added, and the
                                                      version that now holds it
    POST /lookup   {"author": ...}                ->  202 an author lookup (UC4)
    POST /lookup/<id>/choose  {"ids": [...]}      ->  202 the people picked; the
                                                      works follow as a version
    POST /lookup/<id>/more                        ->  202 every record under the
                                                      names; the group filed under
                                                      no work follows as a version
    GET  /health                                  ->  200
    GET  /                                        ->  app/web/

**This is the only server** since Step 16 deleted `lookup/pipeline.py` and
its page; `server.py` at the root is a launcher for it, and `app/web/` is the
reader's page.

**The details endpoint is job-scoped on purpose.** The row the reader opened
belongs to a snapshot, and the snapshot belongs to a job whose store still has
the records behind it — so the id in the URL is the one the page was given, and
a row that has since become a different edition is a 404 rather than the wrong
book. It also keeps the page from re-sending fields the server already holds.

A backend is forced rather than chosen, for the same reason as before: SBN
sends no `Access-Control-Allow-Origin` header of any kind, so a browser cannot
reach it from a static page. One origin, so no CORS anywhere.

**Why the snapshot goes out gzipped.** It is a complete view every time, and the
worst case measured is *Odysseia* at **1,134.6 KB** of JSON — 1,889 edition rows,
216 KB of it the per-row provenance the recovered badge and the leak audit read.
Gzipped that is **96.3 KB** (N02: 763.6 -> 57.2). The rebuild doc's estimate of
"around 150 KB" was tagged **I** and is right only after compression.
"""

import errno
import gzip
import json
import mimetypes
import os
import posixpath
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from app.jobs import Registry
from catalog.http import Ledger
from lookup import stages

PORT = int(os.environ.get("PORT", 8000))
WEB_ROOT = Path(__file__).parent / "web"

# Below this the gzip header costs more than it saves, and an `unchanged` poll
# is ~200 bytes.
GZIP_MIN = 1024

# Other spellings an author-mode row sends with its title (Step 14). S1 tries
# at most `stages.MAX_VARIANTS` of them; this only bounds the request.
MAX_VARIANTS = 12

# A body larger than this is a client error, not a lookup.
MAX_BODY = 64 * 1024


class Handler(BaseHTTPRequestHandler):
    server_version = "book-editions-app/1.0"
    protocol_version = "HTTP/1.1"

    registry = Registry()

    # -- helpers ------------------------------------------------------------

    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        encoding = None
        if len(body) >= GZIP_MIN and "gzip" in self.headers.get("Accept-Encoding", ""):
            body, encoding = gzip.compress(body, 6), "gzip"
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if encoding:
            self.send_header("Content-Encoding", encoding)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write(f"  {self.address_string()} {fmt % args}\n")

    def _guard(self, fn, *args):
        """Never take the server down for one request."""
        try:
            return fn(*args)
        except BrokenPipeError:
            pass                       # the page went away mid-write; normal
        except Exception as exc:
            self.log_message("unhandled: %r", exc)
            self._json({"error": str(exc)}, 500)

    # -- routing ------------------------------------------------------------

    def do_POST(self):
        self.registry.sweep()
        route = urlparse(self.path).path.rstrip("/") or "/"
        if route.startswith("/lookup/") and route.endswith("/add"):
            return self._guard(self._add, route[len("/lookup/"):-len("/add")])
        if route.startswith("/lookup/") and route.endswith("/choose"):
            return self._guard(self._choose, route[len("/lookup/"):-len("/choose")])
        if route.startswith("/lookup/") and route.endswith("/more"):
            return self._guard(self._more, route[len("/lookup/"):-len("/more")])
        if route != "/lookup":
            return self._guard(self._json, {"error": f"no such endpoint: {route}"}, 404)
        return self._guard(self._start)

    def do_GET(self):
        self.registry.sweep()
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        if route == "/health":
            return self._guard(self._json, {"ok": True, "jobs": len(self.registry)})
        if route.startswith("/lookup/"):
            rest = route[len("/lookup/"):]
            job_id, _, tail = rest.partition("/")
            if tail.startswith("edition/"):
                return self._guard(self._details, job_id,
                                   unquote(tail[len("edition/"):]))
            if tail:
                return self._guard(self._json,
                                   {"error": f"no such endpoint: {route}"}, 404)
            return self._guard(self._poll, rest, parse_qs(parsed.query))
        if route.startswith("/api/"):
            return self._guard(self._json, {"error": f"no such endpoint: {route}"}, 404)
        return self._guard(self._static, parsed.path)

    do_HEAD = do_GET

    # -- the two endpoints --------------------------------------------------

    def _start(self):
        """Hand back an id before anything is fetched. Measured under 2 ms."""
        try:
            asked = self._question()
        except ValueError as exc:
            return self._json({"error": str(exc)}, 400)
        job = self.registry.start(*asked)
        self._json({"id": job.id, "version": 0,
                    "poll": f"/lookup/{job.id}?v=0"}, 202)

    def _question(self) -> tuple:
        """The title and author, from a JSON body or the query string.

        A title with no author is asked whose book it is first (decision AN):
        one book the sources agree on is looked up with its author, several are
        a chooser, and the OPAC is never asked without one (`CLAUDE.md` rule 3).
        An author with no title is UC4, which resolves the person first; the
        title comes back empty.
        """
        fields = self._body()
        query = parse_qs(urlparse(self.path).query)
        title = str(fields.get("title") or (query.get("title") or [""])[0]).strip()
        author = str(fields.get("author") or (query.get("author") or [""])[0]).strip()
        if not title and not author:
            raise ValueError("give a title and an author")
        variants = fields.get("variants") or []
        if not isinstance(variants, list) or len(variants) > MAX_VARIANTS or \
                not all(isinstance(v, str) and 0 < len(v) <= 300 for v in variants):
            raise ValueError(f"variants are up to {MAX_VARIANTS} other spellings of the title")
        switches = []
        for name in ("title_spellings", "author_spellings"):
            value = fields.get(name, False)
            if not isinstance(value, bool):
                raise ValueError(f"{name} is true or false")
            switches.append(value)
        return title, author, [v.strip() for v in variants], *switches

    def _body(self) -> dict:
        """The request's JSON object, or `{}` with no body. ValueError if unreadable."""
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError(f"request body over {MAX_BODY} bytes")
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            fields = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ValueError("the body is not JSON")
        if not isinstance(fields, dict):
            raise ValueError("the body is not a JSON object")
        return fields

    def _poll(self, job_id: str, query: dict):
        """A snapshot if the caller is behind, `unchanged` if it is not.

        An unknown id is a **404**, not an empty result: the job was evicted,
        or the server was restarted, and a page that cannot tell those from
        "nothing found" would show a stale list as though it were live.
        """
        job = self.registry.get(job_id)
        if job is None:
            return self._json({"error": "no such job", "id": job_id}, 404)
        try:
            held = int((query.get("v") or ["0"])[0])
        except ValueError:
            held = 0                    # unreadable: send whatever there is
        self._json(job.since(held))

    def _details(self, job_id: str, edition_id: str):
        """One row in full, fetched because the reader opened it.

        **Its own ledger.** The job's was closed when its stages finished, and a
        request on no ledger is a request whose failure reaches no reading
        (`CLAUDE.md` rule 5) — so this opens one for the gesture and hands back
        its counts, and the page can say *Open Library did not answer* rather
        than showing an empty panel that means the same as *nothing to add*.
        """
        job = self.registry.get(job_id)
        if job is None:
            return self._json({"error": "no such job", "id": job_id}, 404)
        with Ledger() as ledger:
            try:
                found = stages.details(job.store, edition_id)
            except KeyError:
                return self._json({"error": "no such edition in this lookup",
                                   "id": edition_id}, 404)
            self._json({**found.edition, "evidence": found.evidence,
                        "requests": len(ledger.calls), "failed": ledger.failed()})

    def _add(self, job_id: str):
        """The reader adds Open Library records to the list (decision J).

        A new version follows and the page polls for it like any other. The
        gesture has its own ledger, like Details, and hands its counts back.
        """
        job = self.registry.get(job_id)
        if job is None:
            return self._json({"error": "no such job", "id": job_id}, 404)
        try:
            keys = self._body().get("keys")
        except ValueError as exc:
            return self._json({"error": str(exc)}, 400)
        if not isinstance(keys, list) or not keys or \
                not all(isinstance(k, str) and k for k in keys):
            return self._json({"error": "give the records to add as a list of keys"}, 400)
        with Ledger() as ledger:
            try:
                result = job.add(keys)
            except RuntimeError as exc:
                return self._json({"error": str(exc)}, 409)
            except KeyError as exc:
                return self._json({"error": exc.args[0] if exc.args else str(exc)}, 400)
            self._json({**result, "requests": len(ledger.calls),
                        "failed_requests": ledger.failed()})

    def _choose(self, job_id: str):
        """The reader picks the people an author lookup offered (UC4).

        409 when the job is not waiting for a choice (a title lookup, or one
        already chosen), 400 for an id it never offered. The works arrive as
        the next version, polled like any other.
        """
        job = self.registry.get(job_id)
        if job is None:
            return self._json({"error": "no such job", "id": job_id}, 404)
        try:
            ids = self._body().get("ids")
        except ValueError as exc:
            return self._json({"error": str(exc)}, 400)
        if not isinstance(ids, list) or not all(isinstance(i, str) and i for i in ids):
            return self._json({"error": "give the people as a list of ids"}, 400)
        choose = getattr(job, "choose", None)
        if choose is None:
            return self._json({"error": "this lookup is not waiting for a choice"}, 409)
        try:
            choose(ids)
        except RuntimeError as exc:
            return self._json({"error": str(exc)}, 409)
        except KeyError as exc:
            return self._json({"error": exc.args[0] if exc.args else str(exc)}, 400)
        self._json({"id": job.id, "version": job.version,
                    "poll": f"/lookup/{job.id}?v={job.version}"}, 202)

    def _more(self, job_id: str):
        """The reader reads past the cap under an author's names (decision BA).

        409 for a title lookup, one still running, or one whose cap cut
        nothing. The group arrives as the next version, polled like any other.
        """
        try:
            # Read even though nothing in it is used: bytes left unread stay on
            # the browser's keep-alive connection and open its next request
            # (`{}GET /lookup/…`, a 501 that stopped the page's polling).
            self._body()
        except ValueError as exc:
            return self._json({"error": str(exc)}, 400)
        job = self.registry.get(job_id)
        if job is None:
            return self._json({"error": "no such job", "id": job_id}, 404)
        more = getattr(job, "read_rest", None)
        if more is None:
            return self._json({"error": "only an author lookup reads under a name"}, 409)
        try:
            more()
        except RuntimeError as exc:
            return self._json({"error": str(exc)}, 409)
        self._json({"id": job.id, "version": job.version,
                    "poll": f"/lookup/{job.id}?v={job.version}"}, 202)

    # -- the page -----------------------------------------------------------

    def _static(self, path: str):
        """`app/web/`, and nothing above it.

        One origin for the page and the JSON, because SBN sends no
        `Access-Control-Allow-Origin` header of any kind and a browser therefore
        cannot reach it from a static page. That is the same reason `server.py`
        has a backend at all; it is not a preference.
        """
        rel = posixpath.normpath(unquote(path)).lstrip("/")
        if rel in ("", "."):
            rel = "index.html"
        target = (WEB_ROOT / rel).resolve()
        if not str(target).startswith(str(WEB_ROOT.resolve()) + os.sep) or not target.is_file():
            body = b"not found"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return
        ctype, _ = mimetypes.guess_type(str(target))
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


def main():
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        print(f"Port {PORT} is already in use — another instance is probably still "
              f"running (it will be serving the code it started with).", file=sys.stderr)
        print(f"  find it:  lsof -nP -iTCP:{PORT} -sTCP:LISTEN", file=sys.stderr)
        print(f"  stop it:  pkill -f server.py      (started as python server.py)", file=sys.stderr)
        print(f"            pkill -f 'app.server'   (started as python3 -m app.server)", file=sys.stderr)
        print(f"  or pick another port:  PORT={PORT + 1} python server.py", file=sys.stderr)
        raise SystemExit(1)
    print(f"book_editions  ->  http://localhost:{PORT}")
    print(f"  POST /lookup  ·  GET /lookup/<id>?v=N  ·  GET /health")
    print("Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        Handler.registry.close()
        server.server_close()


if __name__ == "__main__":
    main()
