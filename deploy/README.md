# Sales CRM — deployment files

This folder runs the published Sales CRM image (`debeski/dlux-crm:sales`) with
Docker Compose, and Composer (`debeski/composer:latest`) deploys, updates and
repairs the stack. It holds no application source and no data: the database, the
uploaded files and the certificates live in Docker volumes and in `media/`.

| File | Purpose |
| --- | --- |
| `compose.yml` | The stack: db, redis, web, **worker**, celery, smtp-relay, caddy, docker-socket-proxy, composer-executor, composer-agent. Keep `name: sales`. Stack schema 5. |
| `start.sh`, `start.ps1` | Composer wrapper 6 (Linux/macOS, Windows). |
| `.composer-channel` | `stable`. Production stays on the stable channel. |
| `.proxy/Caddyfile` | Reverse proxy and automatic HTTPS. |
| `relay/` | Allow-listed outbound requests (exchange rates) made by the Composer agent. |
| `config.json` | Initial system settings, imported on the first start only. |
| `.secrets/.env.template` | Settings template; copy to `.secrets/.env`. |
| `media/`, `logs/`, `imports/` | Uploaded files, logs, and files to import. |

## Requirements

- Linux with Docker Engine and Docker Compose 5.3 or later (DjangoLux uses
  `pre_start` hooks), or Docker Desktop (Windows with the WSL 2 backend, or macOS).
- Internet access on the first start, to pull the images. The deployer
  (`debeski/composer:latest`) must be 1.10.3 or newer; `./start.sh update self`
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
4. Open `BASE_URL/staff/` and sign in as `admin` with `ADMIN_PASS`.
5. Run `./start.sh check`. It must exit 0. The `front-proxy` line stays a warning
   until `DLUX_FRONT_PROXY` is set.

## Upgrading an existing deployment

This is **one upgrade, whichever release the server runs now**. A server on v0.11.x
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

Run everything from the deployment folder (the one holding `compose.yml` and
`.secrets/`) and keep the server's `.secrets/.env`, `media/`, `logs/` and
`imports/`. Do **not** use **Options > Updates and maintenance** for this release:
that card installs only the application image and keeps the old `compose.yml`, and
an image older than DjangoLux 1.16 cannot update itself to this one.

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
   `docker-socket-proxy`, `composer-executor` and `composer-agent`.

   ```bash
   docker ps -a --filter label=com.docker.compose.project=sales \
     --format '{{.Label "com.docker.compose.service"}}\t{{.Names}}\t{{.Status}}'
   ```

   Remove any other row's container (`dlux-updater`, `pgadmin`, `db-backup`) with
   `docker rm -f <name>`; its volume stays. If the stack was started under another
   project name than `sales`, use that name in the filter.
7. **Restart the proxy.** Caddy reads `.proxy/Caddyfile` only when it starts, and
   `./start.sh` does not recreate it while its service definition is unchanged:

   ```bash
   ./start.sh restart caddy
   ```
8. **Verify.**
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

This release's DjangoLux adds its own database tables. To go back, restore the
backup from step 1 with the previous `compose.yml`, `start.sh`, `start.ps1` and
`.proxy/Caddyfile`, put `WEB_IMAGE=debeski/dlux-crm:sales-v<the version you came
from>` in `.secrets/.env`, then run `./start.sh` and `./start.sh restart caddy`. Going back to v0.11.4 or older reopens the
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
