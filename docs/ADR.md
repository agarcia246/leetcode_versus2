# Architecture Decision Record


## [1]. Backend language and framework

Date: 2026-09-28

Status: Superseded by [6]

Context: I am building a small app where users compete in LeetCode challenges against each other. The assignment requires SQLite and one process.

Decision: FastAPI for the API, SQLAlchemy for the SQLite models, and Pydantic models for the request bodies. The React page is built ahead of time and served by the same process from `app/static`.

Alternatives considered: While selecting this, I considered using Django and flask. I decided against both of these because I just needed to implement an api not a full web framework and because of this, fastapi was the most logical choice.

Consequences: the whole project falls under the single container requirement. Only one file is being run, which is the main.py file. Since the API is serving the react frontend we build this before and we keep the static files in app/static

## [2]. Two feature domains that can be split later

Date: 2026-09-30
Status: Superseded by [6]
Context: The match and the problem list are different jobs. The assignment wants both in one process now, with a seam I can point at later.
Decision: Domain 1 is the match: `rooms`, `players`, `room_players`, and `create_room`, `join_room`, `start_room`, `expire_inactive_lobby`, and `assign_match_results`. Domain 2 is the catalog and the solves: `problems`, `topics`, `problem_topics`, `room_problems`, `submissions`, plus `fetch_problems_for_topics`, `upsert_problem`, and `record_match_submissions`. They meet at `room_problems`. Both live in `app/domain/backend/services.py` for now.
Alternatives considered: One CRUD module with no seam, or two Python packages from the start. I rejected two packages because this assignment is one process and the seam is only those calls. I rejected one blob because a later assignment has to split the domains.
Consequences: A later split can lift the catalog out behind `add_problems_to_room` and the submission polling inside `get_room` without rewriting the room-code, host, and score rules. Until then, one SQLite file and one module keep the deployment contract.

## [3]. SQLite schema: topics in a join table

Date: 2026-09-29
Status: Decided
Context: I started from the data. A match needs a room, the people in it, the problems they are racing, and the solves that count. Topics are shared by a lot of problems.
Decision: `rooms` is the center. `players`, `problems`, `submissions`, and `topics` hang off it. Many-to-many links are `room_players`, `room_problems`, and `problem_topics`. Topic names are not stored as one string on `problems`.
Alternatives considered: Drop `problem_topics` and store topics as a long string on `problems`. I rejected that because the same topics show up on many problems, so the names would be copied over and over, and filtering a room by topic would mean parsing that string.
Consequences: The API can be written against a stable shape. `upsert_problem` writes one row per problem and one `problem_topics` row per tag. This is the diagram in the report and in `app/schema.sql`.

## [4]. Testing approach

Date: 2026-10-04
Status: Decided
Context: The grade is on the match rules and the scoring rules, not on FastAPI routes. LeetCode cannot be a dependency of the test run.
Decision: pytest covers `app/domain/backend/services.py`. Room settings, the lobby clock, win/loss, and `record_match_submissions` are called directly. `leetcode_graphql` and `requests.post` are mocked. The measured result is 100% of that module.
Alternatives considered: Hitting the live LeetCode API from pytest, or only testing the routers. I rejected the live calls because they fail offline and depend on a public profile, and the routers are thin wrappers around the service functions.
Consequences: A change to who scores, or to when a lobby expires, fails in `tests/` without a network call. The React page is not part of this number.

## [5]. No in-app editor and no accounts

Date: 2026-10-04
Status: Decided
Context: A match is scored from LeetCode, not from code this app runs. Hosting an editor would mean running other people's code. A password account would duplicate the LeetCode username the score already depends on.
Decision: Players solve on leetcode.com. This app checks that the username exists (`lookup_leetcode_user`), shows problem links, and polls public submissions from `get_room`. Identity is the LeetCode username stored on `players.lc_user`. The page in `frontend/leetcode_vs/src/App.tsx` refreshes the room every 5 seconds. There is no WebSocket and no login.
Alternatives considered: An in-app editor, or pushing score updates over WebSockets instead of the 5-second poll. I rejected both because they add a second product (code execution, or a live channel) that the single process does not need in order to score a match.
Consequences: Scoring fails closed when LeetCode hides a profile. `get_room` stores that on `rooms.poll_error` and still returns the room. The client can be a few seconds behind a solve because it polls instead of receiving a push.

## [6]. The split: catalog and matches as two services

Date: 2026-11-25
Status: Decided
Context: Assignment 2 turns the monolith into two services, one per feature domain, each with its own container and database, and the browser calls them from a static site. ADR-2 drew the seam with `room_problems` and `submissions` on the catalog side, meeting the match at `room_problems`. Building the split showed that every scoring step in `get_room` (`record_match_submissions`, `assign_match_results`) reads those two tables together with `rooms` and `room_players`, so with ADR-2's seam each 5-second poll would have crossed the network several times.
Decision: The seam moved. `services/catalog` owns `problems`, `topics` and `problem_topics`: it knows LeetCode's problem list and nothing about rooms. `services/matches` owns `players`, `rooms`, `room_players`, `room_problems` and `submissions`: everything about a match, including who solved what. `room_problems.problem_id` and `submissions.problem_id` are plain integers holding a catalog ID, with no foreign key. Two calls cross the seam, both from matches to catalog over HTTP (`app/catalog_client.py`, base URL in `CATALOG_URL`): `POST /problems/pick` when a room is created, and `GET /problems?ids=` when a room is shown, to get titles, links and slugs. The UI calls catalog directly only for `GET /filters`. The stack stays FastAPI, SQLAlchemy and Pydantic (ADR-1), but the services no longer serve the page: the React app in `ui/` is built to static files and reads both base URLs from `config.js`. `common.py` is copied into each service instead of shared, so each one builds and deploys on its own. When catalog does not answer (connection refused, timeout after `CATALOG_TIMEOUT_S` = 20 s, or a 5xx other than 502), the client raises `CatalogUnavailable`. Creating a room then fails with a 503 and a clear message, before matches writes anything. Showing a room degrades: players and scores come from matches' own database, `problems` is empty, `problems_unavailable` is true, and LeetCode is not polled that round because scoring needs catalog's slugs. A 502 from catalog means catalog is up but LeetCode failed behind it, and stays a 502.
Alternatives considered: Keeping ADR-2's seam, which I rejected because scoring would need catalog for every poll and a catalog outage would stop matches that are already running. Letting the UI call both services and join problems to rooms in the browser (client side); I kept the room flow server side because creating a room must be atomic (no room without problems) and the brief needs at least one flow to cross the seam server side. A shared database or a shared Python package, which would undo the independence the split is for.
Consequences: ADR-2 held for the domains and not for the line between them: one call per room view crosses the seam instead of a join, and scoring never does. Integrity across the seam is enforced in code, not by the database: catalog only hands out IDs it just stored, and matches skips IDs that catalog no longer returns. Matches waits 20 s for catalog, while each LeetCode call inside catalog has a 5 s timeout; a pick with several pages of LeetCode results can still take longer than 20 s, and then the user gets the 503 and can retry (catalog's upserts are idempotent, so a late finish is harmless). With catalog down, running matches keep their scores but stop counting new solves until it is back. Both services need their own CORS setting (`CORS_ORIGINS`) because the browser calls them directly.

## [7]. Data and migrations

Date: 2026-11-26
Status: Decided
Context: Assignment 1 kept every table in one SQLite file, `data/app.db`, and `init_db` ran `schema.sql` on startup. Assignment 2 gives each service its own database, and the schema has to change later without `CREATE` or `DROP` on boot. A paused Azure SQL database refuses connections for about a minute (error 40613) before it resumes. The two services also cannot share a login: catalog must not be able to open the matches database, or the other way around.
Decision: One SQL Server database per service, and one login per service with access only to its own: `db_ddladmin`, `db_datareader`, and `db_datawriter`. `db/init.sql` creates `catalog` and `matches`, then `catalog_app` and `matches_app`. `catalog_app` has no user in `matches`, and `matches_app` has none in `catalog`, so neither login can open the other's database. Locally both databases sit in one SQL Server container. On Azure they are two serverless databases on one server. `db-init` runs that script once and exits. `ui-build` is the same kind of one-off job, and `ui` is stock nginx. Only `catalog` and `matches` are service containers. The foreign keys on `room_problems.problem_id` and `submissions.problem_id` are gone, because those IDs belong to catalog's database. Compensation is in the code: catalog only returns an ID after `upsert_problem` has stored it, matches leaves out an ID that `GET /problems` no longer knows, and nothing deletes problems. The SQLite schema is ported in `services/<svc>/migrations/001_init.sql`. Keys are `IDENTITY`. Columns with a `UNIQUE` constraint are sized `NVARCHAR`, because SQL Server cannot put `UNIQUE` on `NVARCHAR(MAX)`. Constraints are named (`uq_`, `ck_`, `df_`) so a later file can drop one by name. Timestamps stay UTC ISO strings in `NVARCHAR(40)`, written by `to_db_time`, so `common.py` did not change. If SQL Server reports error 1785 (cycles or multiple cascade paths), `ON DELETE CASCADE` comes off the `player_id` foreign keys. Schema changes go through `app/migrations.py`, the same file in both services, about 40 lines. It applies `migrations/NNN_*.sql` in filename order, each file exactly once, and records the filename in `schema_migrations`. One transaction per file: if the insert into `schema_migrations` fails, the whole file rolls back. `GO` is not SQL, so the runner splits on it before executing each batch. A file is never edited after it has been applied. The next change is a new file. Assignment 1's `data/app.db` was test data, so it was not copied. There is no seed either. Topics and problems come from LeetCode when they are needed, idempotently, through `upsert_problem` and `get_or_create_topic`. Migrations are forward-only. Recovery for a bad one in production: stop deploys. If the file failed, its transaction already rolled back, so nothing changed and the fix is a new file. If it applied but was wrong, fix forward with `00N+1`. If rows were lost, point-in-time restore the Azure database into a new database, then copy the rows back.
Alternatives considered: Alembic, including autogenerate. I rejected it because these 40 lines can be explained one by one, the files are plain T-SQL, and autogenerate would hide the dialect choices (`IDENTITY`, sized `NVARCHAR`, named constraints). `Base.metadata.create_all` on boot, which the unit tests still use against SQLite. I rejected it for the services because it cannot version a change, and startup must not create or drop tables. One shared database. I rejected it because either login could then read or change the other service's tables, which removes the isolation the split is for.
Consequences: `DATABASE_URL` is required and has no default, because a secret cannot have one. Tests set `sqlite://` before importing the app and still build their tables with `create_all`; they move to SQL Server later. Startup calls `wait_for_db` (backoff of about two minutes, long enough for a paused database to resume) and then `run_migrations`. A second start logs that there is nothing to apply. `/health` updates `health_check` in this service's own database and does not call the other service. `db_ddladmin` is on the app login so that login can apply migrations. It still cannot see the other database.
