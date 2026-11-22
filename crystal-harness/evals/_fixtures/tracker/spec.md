# Tracker API

## One-liner
A JSON API for keeping projects and the tasks inside them: tasks move through a small workflow, can wait on other tasks, and can be filtered and paged. There is no user interface.

## Users and jobs
- A script or another service that files tasks under projects, moves them through `todo`, `doing` and `done`, and asks what is left to do.

## Surfaces
- One HTTP API on 127.0.0.1:8765, started with `python3 app.py`. Data lives in a SQLite file, `./tracker.db`.

## Data model
What is said here holds at all times, whichever request last touched the record.

- **Project**: `id` (integer, assigned by the server), `name` (text, 1–60 characters after trimming, unique among all projects ignoring case — two names are the same when their Unicode case-folded forms are equal, so `Straße` and `STRASSE` are one name), `archived` (boolean, false when created), `created_at`, and `task_counts` — an object `{todo, doing, done}` with the number of the project's tasks in each status. Every response that carries a project carries all of these.
- An archived project stays archived, and never gains a task. The tasks already in it can still be read, changed, moved out and deleted.
- **Task**: `id` (integer, assigned by the server), `project_id`, `title` (text, 1–120 characters after trimming), `status` (`todo`, `doing` or `done`; `todo` when created), `priority` (integer 1–5, 3 when omitted), `tags`, `blocked_by`, `completed_at`, `created_at`. Every response that carries a task carries all of these.
- `tags` is an array of text, empty when omitted. Tags are sent as an array of at most 5 strings; each is trimmed and lower-cased and must then be 1–20 characters long, and a tag that repeats an earlier one after that is dropped. A task's tags are always held and returned in that form, in the order sent.
- `blocked_by` is the ids of the tasks this one waits on, ascending. They are always tasks that exist. A task never waits on itself, and blocking relations never form a cycle.
- `completed_at` is a timestamp while the status is `done`, and null otherwise.

## Behaviour and states

### Projects
- `POST /projects` with `{name}` creates a project and returns it with status 201.
- `GET /projects` lists the projects that are not archived, in creation order. `include_archived` is `true` or `false` (the default); with `true` the archived ones are listed as well.
- `GET /projects/{id}` returns one project.
- `POST /projects/{id}/archive` archives the project and returns it with status 200. Archiving an archived project is also 200.
- `DELETE /projects/{id}` returns 204 and permanently removes the project and every task in it.

### Tasks
- `POST /projects/{id}/tasks` with `{title, priority?, tags?}` creates a task in that project and returns it with status 201.
- `GET /tasks/{id}` returns one task.
- `PATCH /tasks/{id}` with any of `{title, priority, tags}` changes those fields and returns the task with status 200. A body with any other field, or with none of the three, is 422. `status` and `project_id` are not changed this way.
- `DELETE /tasks/{id}` returns 204 and permanently removes the task.
- `POST /tasks/{id}/move` with `{project_id}` moves the task to that project and returns it with status 200. Moving a task to the project it is already in changes nothing and is 200.

### Listing tasks
- `GET /tasks` returns `{"items": [...], "total": n}`. `items` is sorted by priority, highest first, and within one priority by id, ascending. `total` is the number of tasks that match the filters.
- Filters, all optional and combined with AND: `project_id` (an integer; one that matches no project gives an empty list), `status` (one of the three), `tag` (trimmed and lower-cased before matching; a task matches when it carries that tag).
- Paging: `limit` (integer 1–100, 20 when omitted) and `offset` (integer 0 or more, 0 when omitted).

### Workflow
- `POST /tasks/{id}/transition` with `{to}` changes the status and returns the task with status 200. The allowed moves are `todo → doing`, `doing → done`, `doing → todo`, and `done → doing` (re-opening). Any other move, including to the status the task already has, is refused.
- A task cannot enter `done` while a task it waits on is not `done`. Re-opening a task does not change tasks that are already `done`.

### Blocking
- `PUT /tasks/{id}/blockers/{blocker_id}` records that the task waits on the blocker and returns the task with status 200. Doing it again is also 200 and changes nothing. The two tasks may be in different projects.
- `DELETE /tasks/{id}/blockers/{blocker_id}` removes the relation and returns 204; 404 when the task is not waiting on that blocker.

### Persistence
- Projects, tasks, tags and blocking relations persist across a restart of the server.

## Status codes
- 400: the request body is not valid JSON, or holds text that is not valid Unicode.
- 404: an id in the path, or a `project_id` in the body of a move, matches no project or task; or the path is one the API does not have.
- 405: a path the API has, with a method it does not support there.
- 409: the request is well-formed, but what it asks for would break a rule above — a name that is taken, a move the workflow refuses, anything the data model says never happens. Nothing changes.
- 422: the request is malformed — the body is valid JSON but not an object, a field is missing or of the wrong type or outside its range, a query parameter is not one of its allowed values. Nothing changes.
- A request that is wrong in more than one of these ways gets one of the statuses that apply; which one is not specified.

## Non-goals
- No authentication, no user interface, no renaming of projects, no un-archiving, no due dates, no comments.

## Feature ordering
1. Projects and tasks
2. Workflow and blocking
3. Listing, filters and paging
4. Archiving, moving and deleting

## Open questions
- None. The stack is fixed by `.harness/config.json`: one Python 3 standard-library HTTP server in `app.py`, SQLite, `unittest`. No third-party packages.
