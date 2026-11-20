# Notes API

## One-liner
A tiny JSON API for keeping short text notes. There is no user interface.

## Users and jobs
- A script or another service that needs to store, list and remove short notes over HTTP.

## Surfaces
- One HTTP API on 127.0.0.1:8765, started with `python3 app.py`. Data lives in a SQLite file, `./notes.db`.

## Data model
- **Note**: `id` (integer, assigned by the server), `title` (text, required, 1–100 characters after trimming), `body` (text, optional, empty when omitted).

## Behaviour and states
- `POST /notes` with a JSON body `{title, body?}` creates a note and returns it — including the `body` that was sent — with status 201. `title` is required, 1–100 characters after trimming; otherwise the response is 422 and nothing is stored.
- `GET /notes` lists all notes in creation order, oldest first. `GET /notes/{id}` returns one note, or 404 for an unknown id.
- `DELETE /notes/{id}` removes the note permanently and returns 204; afterwards `GET /notes/{id}` returns 404 and the note is gone from the datastore. An unknown id returns 404.
- Notes persist across a restart of the server.

## Edge cases
- Invalid JSON in a request body returns 400.

## Non-goals
- No authentication, no user interface, no pagination, no editing of an existing note.

## Feature ordering
1. Create and read notes
2. List notes
3. Delete notes

## Open questions
- None. The stack is fixed by `.harness/config.json`: one Python 3 standard-library HTTP server in `app.py`, SQLite, `unittest`. No third-party packages.
