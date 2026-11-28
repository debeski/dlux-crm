# Sales CRM — deployment files

This folder runs the published Sales CRM image (`debeski/dlux-crm:sales`) with
Docker Compose, and Composer (`debeski/composer:latest`) deploys, updates and
repairs the stack. It holds no application source and no data: the database, the
uploaded files and the certificates live in Docker volumes and in `media/`.

| File | Purpose |
| --- | --- |
| `compose.yml` | The stack: db, redis, web, **worker**, celery, smtp-relay, caddy, composer-executor, composer-agent. Keep `name: sales`. Stack schema 5. |
| `start.sh`, `start.ps1` | Composer wrapper 8 (Linux/macOS, Windows). |
| `.composer-channel` | `stable`. Production stays on the stable channel. |
| `.composer-image` | Not shipped: Composer writes it on this server when it pins its own signed release (`./start.sh agent update`), and the wrappers then run that digest. |
| `.proxy/Caddyfile` | Reverse proxy and automatic HTTPS. |
| `relay/` | Allow-listed outbound requests (exchange rates) made by the Composer agent. |
| `config.json` | Initial system settings, imported on the first start only. |
| `.secrets/.env.template` | Settings template; copy to `.secrets/.env`. |
| `media/`, `logs/`, `imports/` | Uploaded files, logs, and files to import. |

## Requirements

- Linux with Docker Engine and Docker Compose 5.3 or later (DjangoLux uses
  `pre_start` hooks), or Docker Desktop (Windows with the WSL 2 backend, or macOS).
- Internet access on the first start, to pull the images. The deployer
  (`debeski/composer:latest`) must be 1.11.0 or newer; `./start.sh update self`
  refreshes it.
- For a public site: DNS records for every hostname in `CADDY_SITE_ADDRESS`
  pointing at this machine, and inbound TCP 80 and 443 open.

## How the stack runs

- The **`worker`** service applies the database migrations before the application
  starts, and runs backups and DjangoLux's scheduled work. The **`celery`** service
  runs the one project task, the exchange-rate refresh (every 3 hours and once at
  start); it applies no migrations.
- Stored files (purchase-invoice and expense attachments) are private: the proxy
  asks the app before sending any of them. That works only with the application
  image behind this folder's `.proxy/Caddyfile`, so an upgrade pulls the image
  first.
- **`DLUX_FRONT_PROXY`** is the address of a proxy or TLS terminator in front of
  this server. Unset, Caddy trusts every private address for `X-Forwarded-For`,
  and `./start.sh check` shows a `front-proxy` warning. That warning is by design
  and harmless when Caddy itself faces the internet (see
  [DLUX_FRONT_PROXY](#dlux_front_proxy)).
- `composer-agent` has no Docker access: `composer-executor` alone holds the Docker
  socket, performs updates and answers the agent's few reads.
- **`DLUX_UPDATE_POLICY`** (`all` by default, `inline` or `none`) limits which
  updates the app's Updates card may request. Commands run from this folder are
  not limited.
- Redis keeps RDB snapshots (`--appendonly no --save 60 1`): a hard stop of the
  server loses at most about a minute of cache and sessions, and Redis always
  starts again.
- The database container's environment is only what PostgreSQL reads, so changing
  the application image never restarts it. The database name is `POSTGRES_DB`
  (default `sales_db`); keep the name your server's database already has.
- Sales Report to Excel writes customer names, descriptions and numbers as text: a
  value starting with `=` never runs as a spreadsheet formula.

## First installation

1. Copy this folder to the server, e.g. `/opt/crm-sales` (Windows: `C:\crm`).
2. Create the settings file and fill in every `CHANGE_ME`:

   ```bash
   cp .secrets/.env.template .secrets/.env
   chmod 600 .secrets/.env
   openssl rand -hex 32   # run once per secret
   ```

   Set `BASE_URL`, `ALLOWED_URLS`, `ALLOWED_HOSTS` and the `CADDY_*` values to
   your hostname. For a single PC or a local network, use the plain-HTTP block
   in the template instead.
3. Start the stack:

   ```bash
   ./start.sh
   ```

   Windows: `powershell -ExecutionPolicy Bypass -File .\start.ps1`

   The first start pulls the images, applies the migrations, imports
   `config.json` and starts every service.
4. Open `BASE_URL/staff/` and sign in as `admin` with `ADMIN_PASS`. With
   `ADMIN_PASS` left empty or `admin`, no account is created: `./start.sh` asks for
   the password at a terminal on the first start, and `./start.sh check --fix` asks
   while it is empty.
5. Pin Composer to its signed release: `./start.sh agent update`. It writes
   `.composer-image` and pins the resident pair to the same digest; from then on
   the wrappers run that digest.
6. Run `./start.sh check --fix`, then `./start.sh check`. It must exit 0. The fix
   gives the app's non-root user group access to `media/`, `logs/` and the data
   volumes (without it `check` shows an `app-permissions` warning). The
   `front-proxy` line stays a warning until `DLUX_FRONT_PROXY` is set, and
   `postgres-password` warns while `POSTGRES_PASSWORD` is the published default
   `admin_pass`.

## Upgrading an existing deployment

Run everything from the deployment folder (the one holding `compose.yml` and
`.secrets/`) and keep the server's `.secrets/.env`, `media/`, `logs/` and
`imports/`. Do **not** use **Options > Updates and maintenance** for this release:
that card installs only the application image, and this release also needs
Composer 1.11 and its stack-file repairs.

**Which section applies depends on the stack files, not on the image.** Run
`docker compose ps --services`. If the list has no `worker` but still has
`docker-socket-proxy` and `celery`, the server runs stack schema 4, the v0.12.x
files. That is still true if the Updates card has already moved its image to v0.13.0.
Such a server follows **From v0.12.x or older**, which copies this release's files
and adds `worker`.

A schema-4 stack whose image an Updates card moved to DjangoLux 1.16 can sit
behind the maintenance page ("Application update in progress") with every service
healthy. The update raised the maintenance flag, and only the `worker` service
lowers it. Bring the site back first:
1. Back up.
2. Check that `deploy-status.json` reads `ready`:

   ```bash
   docker compose exec caddy cat /opt/dlux-runtime/state/deploy-status.json
   ```

3. Move the flag aside. The file is kept for review:

   ```bash
   docker run --rm -v sales_dlux_runtime:/rt alpine \
     mv /rt/state/maintenance /rt/failed/maintenance-manual
   ```

   `sales_dlux_runtime` is the runtime volume's name in this stack; check it with
   `docker volume ls`.

Then upgrade. Start no other update from the card on that stack: each one raises
the flag again.

### From v0.13.0

A server on v0.13.0 runs Composer 1.10.x with wrapper 6. `check --fix` brings its
stack files to this release's shape, so no file needs copying by hand.

1. **Back up.** In the app, create a backup under Options > Backup & Restore and
   download it, and copy the `media/` folder. Keep a database dump too if you have
   one. The rollback below needs this backup.
2. **Pull the new application image first.** This restarts nothing: the stack keeps
   running the old image until step 5, and `check --fix` never recreates a service
   onto a pulled image.

   ```bash
   docker pull debeski/dlux-crm:sales
   ```

   If `.secrets/.env` has a `WEB_IMAGE=` line pinning an old version, remove it.
3. **Update Composer to 1.11.0 or newer:** `./start.sh update self`. Wrapper 6
   pulls `debeski/composer:latest`; `./start.sh check` then reports
   `versions: Deploying composer 1.11.x`.
4. **Repair the stack files:** `./start.sh check --fix`. At a terminal it lists the
   repairs and asks once, and asks whether to switch Redis to snapshots (answer
   `y`). It:
   - replaces `start.sh` and `start.ps1` with wrapper 8;
   - removes `docker-socket-proxy`: its service, the agent's `DOCKER_HOST` and its
     `depends_on` entry, and the running container (`composer-executor` answers the
     agent's Docker reads);
   - adds the stored-file headers to `.proxy/Caddyfile` (`nosniff`, a sandbox
     `Content-Security-Policy`, `Content-Disposition: attachment` for anything but
     images and PDF) and the maintenance page's `Content-Security-Policy`;
   - passes `DLUX_UPDATE_POLICY` (`all` unless `.secrets/.env` sets it) to `web`,
     `worker`, `celery`, `composer-executor` and `composer-agent`;
   - switches Redis from the append-only file to RDB snapshots
     (`--appendonly no --save 60 1`, its memory limit kept). A few users may have to
     sign in again.

   Each replaced file is kept under `.xclude/composer-check/`. It recreates `caddy`,
   `redis` and the resident pair; `web`, `worker` and `celery` keep the old image
   until step 5. If it says `composer-agent` must be running to publish the
   maintenance page, run step 5 and then `check --fix` once more.
5. **Deploy:** `./start.sh`. It recreates the application services on the new
   image; `worker` applies the migrations before `web` serves. Wait for it to
   finish. `docker compose ps` must list no `docker-socket-proxy`; if it does,
   `docker compose up -d --remove-orphans` removes it.
6. **Pin Composer:** `./start.sh agent update`. It verifies Composer's signed
   release, writes its digest to `.composer-image` and to the resident block in
   `compose.yml`, and recreates the pair on it. From then on the wrappers run that
   digest, and `update self` / `agent update` move it.
7. **Verify:** `./start.sh check` exits 0, with `stored-files`, `redis-persistence`,
   `update-policy` and `docker-proxy` OK. It warns on an empty or `admin`
   `ADMIN_PASS` (`admin-pass`; harmless when the admin account exists, which is
   never changed) and on the published default `POSTGRES_PASSWORD`
   (`postgres-password`: change it inside PostgreSQL first, then in `.secrets/.env`).
   `front-proxy` stays a warning until `DLUX_FRONT_PROXY` is set. Sign in, open
   the **Sales Report** page (`/staff/sales/report/`) and download the Excel file,
   and check that `./start.sh log -n 100 celery` shows
   `finance.tasks.refresh_market_rates` succeeding.

### From v0.12.x or older

This is **one upgrade, whichever older release the server runs**. A server on v0.11.x
or v0.12.x does not need an intermediate step: the steps below also deliver what
the releases in between changed. In particular, **stored files
(purchase-invoice and expense attachments) were reachable without signing in up to
v0.11.4**; this upgrade closes that, and the order in steps 2, 4 and 7 is what
closes it: image first, then the release files, then `./start.sh restart caddy`.
Updating only the image keeps the old Caddyfile, which still serves stored files
without login. A server whose Caddy and Compose files are older than v0.11.4 (the
public site served from an old portfolio folder, a `dlux-updater`, `pgadmin` or
`db-backup` service) takes the same steps; step 6 removes what the new stack no
longer has.

These steps copy this release's files over the server's (step 4) rather than
leaving them to `check --fix`. An image older than DjangoLux 1.16 cannot
update itself to this one.

1. **Back up.** In the app, create a backup under Options > Backup & Restore and download
   it, and copy the `media/` folder. Keep a database dump too if you have one. Note
   the database name (`docker compose exec db psql -U <POSTGRES_USER> -l`): if it is
   not `sales_db`, `.secrets/.env` must set `POSTGRES_DB` to it before step 5. Note
   the Compose project name too (`docker compose ls`): this stack is `sales`. A
   server still running under another name (`switch_pos` or `sales-crm`, the
   earliest releases) keeps its data in volumes of that name, which the new stack
   does not see: stop here and move the data first (back up, start the new stack,
   restore the backup).
2. **Pull the new application image first.** This restarts nothing: the stack keeps
   running the old image until step 5. The new proxy file asks the app's media
   check, which only the new image answers.

   ```bash
   docker pull debeski/dlux-crm:sales
   ```

   If `.secrets/.env` has a `WEB_IMAGE=` line pinning an old version, remove it.
3. **Refresh the Composer deployer:** `./start.sh update self`. An older wrapper
   spells it `./start.sh self update` (wrappers 3 to 5) or `./start.sh update-self`
   (wrapper 1).
4. **Copy this release's files over the server's:** `compose.yml`, `start.sh`,
   `start.ps1`, `.proxy/Caddyfile`, `.composer-channel` and `relay/`. Move the old
   copies, and `.proxy/maintenance.html` (Composer now serves the update progress
   page), into `.xclude/` first. Do not touch `.secrets/.env`; if the old
   `compose.yml` had local edits, move them into `.secrets/.env` variables first.
   `compose.yml` carries no site address of its own (its defaults are plain HTTP on
   `localhost`), so `.secrets/.env` must set `BASE_URL`, `ALLOWED_URLS`,
   `ALLOWED_HOSTS`, `CADDY_SITE_ADDRESS` and `CADDY_PRIMARY_URL` (and
   `CADDY_ERP_ADDRESS` if the old hostname is kept); copy any that are missing from
   `.secrets/.env.template` and fill them in. Then repair and check:

   ```bash
   ./start.sh check --fix
   ```

   With this release's files `check --fix` leaves `compose.yml` as it is. It
   restamps `.secrets/.env` if that file still carries an older stack-schema stamp
   (a file with no stamp, from before v0.12.0, is only noted: nothing to do), and
   gives the app's non-root user group access to its data (`media/`, `logs/` and
   the `static` and `dlux_runtime` volumes; it prints a manifest that
   `composer app-permissions revert` undoes). If it
   says `composer-agent` must be running to publish the maintenance page, run
   step 5 and then `check --fix` once more.
5. **Deploy:** `./start.sh`. This adds the `worker` service, restarts the
   application containers, applies DjangoLux's own migrations and, on a server
   coming from an earlier stack, restarts the database once for a few seconds (its
   environment changed; its data stays in the volume). Its migrations move the
   stored settings and preferences to their new names. Everyone is signed out once
   (the session cookie is renamed), and a form left open across the upgrade asks to
   be reloaded. Wait for the first start to finish.
6. **Remove containers the new stack no longer has.** Compose leaves the container
   of a service that left `compose.yml` running. The new stack has exactly these
   services: `db`, `redis`, `smtp-relay`, `caddy`, `web`, `worker`, `celery`,
   `composer-executor` and `composer-agent`.

   ```bash
   docker ps -a --filter label=com.docker.compose.project=sales \
     --format '{{.Label "com.docker.compose.service"}}\t{{.Names}}\t{{.Status}}'
   ```

   Remove any other row's container (`dlux-updater`, `pgadmin`, `db-backup`,
   `docker-socket-proxy`) with
   `docker rm -f <name>`; its volume stays. If the stack was started under another
   project name than `sales`, use that name in the filter.
7. **Restart the proxy.** Caddy reads `.proxy/Caddyfile` only when it starts, and
   `./start.sh` does not recreate it while its service definition is unchanged:

   ```bash
   ./start.sh restart caddy
   ```
8. **Verify.**
   - `./start.sh agent update` pins Composer to its signed release.
   - `./start.sh check` exits 0: `stack-schema` 5, `stored-files` and the task
     worker check OK (`front-proxy` stays a warning until it is set).
   - Signed out, a stored attachment must answer `403`. With your `BASE_URL` in
     place of `https://crm.example.com`:

     ```bash
     f=$(find media/purchase_invoices media/finance/expenses -type f 2>/dev/null | head -n1); echo "${f:-no stored attachments}"; [ -z "$f" ] || curl -s -o /dev/null -w '%{http_code}\n' "https://crm.example.com/$f"
     ```

     On Windows, open `BASE_URL/media/purchase_invoices/<a file in that folder>` in a
     private browser window instead. Anything but `403` means the proxy still runs
     the old Caddyfile: check that `.proxy/Caddyfile` was replaced, and repeat step 7.
   - The exchange-rate refresh runs: `./start.sh log -n 100 celery` shows
     `finance.tasks.refresh_market_rates` succeeding shortly after the start. If it
     shows `RelayError: timeout ... The agent did not answer in time`, the Composer
     agent was still busy with its start-up package check (minutes on a slow
     connection): wait, then `./start.sh restart celery` runs it again; otherwise the
     next run comes within 3 hours and the last known rates stay in use meanwhile.
   - Sign in, open the **Sales Report** page (`/staff/sales/report/`) and download the Excel file.

### DLUX_FRONT_PROXY

Set it when a proxy or TLS terminator sits in front of Caddy: add
`DLUX_FRONT_PROXY=<address>` to `.secrets/.env` (several addresses or networks:
space-separated, no quotes), then run `./start.sh` and `./start.sh restart caddy`.
Only those addresses are trusted for `X-Forwarded-For`, so a user who reaches
Caddy's port directly can no longer choose the address recorded for the login
lockout and the activity log. `DLUX_FRONT_PROXY=` (empty) trusts none. With Caddy
facing the internet directly there is nothing to name: the default
(private addresses only) is safe, and the `front-proxy` warning can stay.

### Rolling back

Composer's downgrade guard refuses to deploy an older application image, or one
that does not know the migrations this release applied, so going back means
restoring the backup from step 1 and forcing the deploy, in this order:

1. In `.secrets/.env` set `WEB_IMAGE=debeski/dlux-crm:sales-v<the version you came
   from>`. Keep this release's stack files and Composer: they run that image too.
2. Restore the backup from step 1: Options > Backup & Restore, choosing **Ignore
   database version mismatch** (the backup is from the version you are going back
   to), or load your database dump.
3. Deploy the older image at once: `./start.sh --force`. The forced deploy becomes
   the guard's new record.
4. Clear the cache, which still holds this release's settings, and restart:

   ```bash
   docker compose exec redis redis-cli -n 1 FLUSHDB
   ./start.sh restart
   ```

   Everyone signs in again. Going back to v0.11.4 or older reopens the
   stored-files exposure: do it only to recover.

## Updating later

Back up first: **Options > Backup & Restore** in the app, or keep a database dump.

- In the app: **Options > Updates and maintenance** shows a new application
  image when one is published. Install it there.
- Or from this folder: `./start.sh update`. It refreshes the Composer deployer,
  pulls the new images and recreates the services; migrations run on start.

## Everyday commands

Run from this folder (Windows: prefix with
`powershell -ExecutionPolicy Bypass -File .\start.ps1`):

| Task | Command |
| --- | --- |
| Start, or apply a changed `.secrets/.env` | `./start.sh` |
| Update the images | `./start.sh update` |
| Update only the Composer deployer | `./start.sh update self` |
| Check the deployment | `./start.sh check` |
| Repair what the check found | `./start.sh check --fix` |
| Stop (removes the containers, keeps the data) | `./start.sh stop` |
| Restart | `./start.sh restart` |
| Last 200 log lines of a service | `./start.sh log -n 200 web` |

Never pass `-v` or `-p` to `stop`: they delete the database and every other volume.
