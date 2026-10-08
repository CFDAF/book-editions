#!/usr/bin/env python3
"""Local web page for book_editions.

    python server.py            ->  http://localhost:8000

A launcher for `app/server.py`, which holds the server: a job id at once,
versioned snapshots after it (decision M). `PORT` picks another port.
"""

from app.server import main

if __name__ == "__main__":
    main()
