# Tracker API

## One-liner
A JSON API for keeping projects and the tasks inside them: tasks move through a small workflow, can wait on other tasks, and can be filtered and paged. There is no user interface.

## Users and jobs
- A script or another service that files tasks under projects, moves them through `todo`, `doing` and `done`, and asks what is left to do.

## Surfaces
- One HTTP API on 127.0.0.1:8765, started with `python3 app.py`. Data lives in a SQLite file, `./tracker.db`.

## Data model
- **Project**: `id` (integer, assigned by the server), `name` (text, 1–60 characters after trimming, unique among all projects ignoring case), `archived` (boolean, false when created), `created_at`, and `task_counts` — an object `{todo, doing, done}` with the number of the project's tasks in each status. Every response that carries a project carries all of these.
- **Task**: `id` (integer, assigned by the server), `project_id`, `title` (text, 1–120 characters after trimming), `status` (`todo`, `doing` or `done`; `todo` when created), `priority` (integer 1–5, 3 when omitted), `tags` (array of text, empty when omitted), `blocked_by` (array of the ids of the tasks this one waits on, ascending), `completed_at` (a timestamp while the status is `done`, otherwise null), `created_at`. Every response that carries a task carries all of these.
- **Tags**: sent as an array of at most 5 strings. Each is trimmed and lower-cased and must then be 1–20 characters long; a tag that repeats an earlier one after that is dropped. What is stored and returned is the result, in the order sent.

## Behaviour and states

### Projects
- `POST /projects` with `{name}` creates a project and returns it with status 201. An invalid name is 422; a name another project already has, ignoring case, is 409.
- `GET /projects` lists the projects that are not archived, in creation order. `GET /projects?include_archived=true` lists the archived ones as well.
- `GET /projects/{id}` returns one project.
- `POST /projects/{id}/archive` archives the project and returns it with status 200. Archiving an archived project is also 200. There is no way to un-archive.
- An archived project accepts no new tasks: creating a task in it, or moving a task into it, is 409. The tasks already in it can still be read, changed, moved out and deleted.
- `DELETE /projects/{id}` returns 204 and permanently removes the project, every task in it, and every blocking relation those tasks were part of — a task in another project that was waiting on one of them no longer is.

### Tasks
- `POST /projects/{id}/tasks` with `{title, priority?, tags?}` creates a task in that project and returns it with status 201. Invalid input is 422 and nothing is stored.
- `GET /tasks/{id}` returns one task.
- `PATCH /tasks/{id}` with any of `{title, priority, tags}` changes those fields, under the same rules as creation, and returns the task with status 200. A body with any other field, or with none of the three, is 422 and nothing changes. `status` and `project_id` are not changed this way.
- `DELETE /tasks/{id}` returns 204 and permanently removes the task and every blocking relation it was part of: the tasks that were waiting on it no longer are.
- `POST /tasks/{id}/move` with `{project_id}` moves the task to that project and returns it with status 200. A `project_id` that is not an integer is 422.

### Listing tasks
- `GET /tasks` returns `{"items": [...], "total": n}`. `items` is sorted by priority, highest first, and within one priority by id, ascending.
- Filters, all optional and combined with AND: `project_id` (an integer; one that matches no project gives an empty list), `status` (one of the three), `tag` (trimmed and lower-cased before matching; a task matches when it carries that tag).
- Paging: `limit` (integer 1–100, 20 when omitted) and `offset` (integer 0 or more, 0 when omitted). `total` is the number of tasks that match the filters, whatever `limit` and `offset` are.
- A `status` that is not one of the three, a `project_id` that is not an integer, or a `limit` or `offset` outside its range is 422.

### Workflow
- `POST /tasks/{id}/transition` with `{to}` changes the status and returns the task with status 200. The allowed moves are `todo → doing`, `doing → done`, `doing → todo`, and `done → doing` (re-opening). Any other move, including to the status the task already has, is 409 and nothing changes. A `to` that is not one of the three statuses is 422.
- Entering `done` sets `completed_at`; leaving `done` sets it back to null.

### Blocking
- `PUT /tasks/{id}/blockers/{blocker_id}` records that the task waits on the blocker and returns the task with status 200. Doing it again is also 200 and changes nothing. The two tasks may be in different projects.
- A task cannot wait on itself, and blocking relations never form a cycle of any length (A waits on B, B on C, C on A): a request that would create one is 409 and nothing changes.
- `DELETE /tasks/{id}/blockers/{blocker_id}` removes the relation and returns 204; 404 when the task is not waiting on that blocker.
- A task cannot enter `done` while any task it waits on is not `done`: the transition is 409. Re-opening a blocker afterwards does not change tasks that are already `done`.

### Persistence
- Projects, tasks, tags and blocking relations persist across a restart of the server.

## Edge cases
- A request body that is not valid JSON is 400. Valid JSON that is not an object is 422.
- An id in a path that matches no project or task is 404; so is a `project_id` in the body of a move. A path the API does not have is 404. A path the API has, with a method it does not support there, is 405.

## Non-goals
- No authentication, no user interface, no renaming of projects, no un-archiving, no due dates, no comments.

## Feature ordering
1. Projects and tasks
2. Workflow and blocking
3. Listing, filters and paging
4. Archiving, moving and deleting

## Open questions
- None. The stack is fixed by `.harness/config.json`: one Python 3 standard-library HTTP server in `app.py`, SQLite, `unittest`. No third-party packages.
