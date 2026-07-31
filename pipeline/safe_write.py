"""Crash-safe JSON writing for the files a browser or a later run reads.

open(path, "w") truncates the file before the first byte of new content is
written, so a process that dies part way through a dump leaves a half-written
or empty file behind where a good one used to be. That matters here because
forecast.yml commits with `if: always()` — a blend step that crashes mid-write
still gets its truncated output committed, pushed, and served by Pages, and
app.js can only log "keeping previous render", which on a cold load is a blank
page until the next 6-hourly run.

Writing to a temp file in the same directory and renaming keeps the previous
good file intact until the new one is complete; os.replace is atomic within a
filesystem, so a reader sees either the old file or the new one, never a
partial one.
"""
import json
import os


def write_json(path, payload, **dump_kwargs):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(payload, f, **dump_kwargs)
            # The rename only orders against data that reached the OS; without
            # these two the file can be present but empty after a host crash.
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        # Never leave the temp file behind to be picked up by `git add data/`.
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
