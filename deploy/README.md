# Sales CRM — deployment files

This folder runs the published Sales CRM image (`debeski/dlux-crm:sales`) with
Docker Compose. It holds no application source and no data: the database, the
uploaded files and the certificates live in Docker volumes and in `media/`.

## Requirements

- Linux with Docker Engine and Docker Compose 5.3 or later (DjangoLux uses
  `pre_start` hooks), or Docker Desktop (Windows with the WSL 2 backend, or macOS).
- Internet access on the first start, to pull the images.
- For a public site: DNS records for every hostname in `CADDY_SITE_ADDRESS`
  pointing at this machine, and inbound TCP 80 and 443 open.

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
5. Run `./start.sh check`. It must report no findings.

## Updating

Back up first: **Options > Backups** in the app, or keep a database dump.

- In the app: **Options > Updates and maintenance** shows a new application
  image when one is published. Install it there.
- Or from this folder: `./start.sh update`. It refreshes the Composer deployer,
  pulls the new images and recreates the services; migrations run on start.

Stacks set up before Sales CRM 0.12.0 still serve the update progress page from
`.proxy/maintenance.html`. After updating, move that file into `.xclude/.proxy/`,
then open **Options > Operations**, run the deployment check and choose **Apply
repairs** (or run `./start.sh check --fix`). Composer then serves its own page and
archives the old files under `.xclude/composer-check/`. Leaving the file in place
keeps it as a project override instead.

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

## Files

| Path | Purpose |
| --- | --- |
| `compose.yml` | The services. Edit settings in `.secrets/.env`, not here. |
| `start.sh`, `start.ps1` | Composer wrapper (version 6). |
| `.composer-channel` | `stable`. Production stays on the stable channel. |
| `.proxy/Caddyfile` | Reverse proxy and automatic HTTPS. |
| `relay/` | Allow-listed outbound requests (exchange rates) made by the Composer agent. |
| `config.json` | Initial system settings, imported on the first start only. |
| `.secrets/.env` | Your settings and secrets. Keep it private and backed up. |
| `media/`, `logs/`, `imports/` | Uploaded files, logs, and files to import. |
