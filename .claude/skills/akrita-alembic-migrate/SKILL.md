---
name: akrita-alembic-migrate
description: >
  Apply or generate Alembic migrations for the AKRITA Postgres database. Use for
  "run the migration", "alembic upgrade head", "downgrade the DB", "generate a
  revision", or after adding/changing a SQLAlchemy model. Mutates the database; on
  this host the localhost DSN IS the live DB (13 users / 447 traces). Requires the
  token MIGRATE-CONFIRMED before any upgrade/downgrade. Never auto-run.
user-invocable: true
disable-model-invocation: true
allowed-tools: Bash(.venv/bin/alembic:*), Bash(pg_dump:*), Bash(.venv/bin/python:*), Read
---

# AKRITA Alembic migrate

> **Confirmation gate.** Do NOT run `alembic upgrade`/`downgrade` until the user's
> message contains the literal token `MIGRATE-CONFIRMED`. If it is absent, stop and
> ask them to re-invoke with it. Read-only inspection (`current`, `history`) and the
> `pg_dump` backup may run without the token.
>
> **The localhost DSN is the LIVE database** (`postgresql://akrita:akrita@localhost:5432/akrita`,
> sourced via `shared/config.py` → `settings.sync_postgres_dsn`). Treat every
> upgrade/downgrade as production.

## 1. Inspect (safe)
```bash
cd /home/ubuntu/akrita
.venv/bin/alembic current      # where the DB is now (expect head 0003)
.venv/bin/alembic history      # the revision chain
```

## 2. Back up first (always, before mutating)
```bash
PGPASSWORD=akrita pg_dump -h 127.0.0.1 -U akrita -d akrita > /tmp/akrita_pre_$(date +%Y%m%d_%H%M%S).sql
```
Report the backup path + size.

## 3. Apply (GATED — needs MIGRATE-CONFIRMED)
```bash
.venv/bin/alembic upgrade head        # apply pending migrations
# or a specific target:  .venv/bin/alembic upgrade <rev>
# downgrade (extra caution):  .venv/bin/alembic downgrade -1
```

## 4. Generate a new revision (review before applying)
```bash
.venv/bin/alembic revision --autogenerate -m "<message>"
```
Then **read the generated file** under `migrations/versions/` and confirm the SQL is
correct (autogenerate misses data backfills, server defaults on NOT NULL columns,
and enum changes). New migrations are additive-by-default; verify any column added
to a populated table is nullable or has a server_default. Only then apply via step 3.

## Verify after
```bash
.venv/bin/alembic current
.venv/bin/python -c "import psycopg2;c=psycopg2.connect(host='127.0.0.1',port=5432,user='akrita',password='akrita',dbname='akrita');cur=c.cursor();cur.execute('select count(*) from users');print('users',cur.fetchone()[0])"
```
Existing traces stay verifiable across migrations because verification re-hashes the
IPFS-pinned body, not DB rows — never re-pin or re-hash committed traces.
