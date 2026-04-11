# Cloudflare Private Remote Access

This project already serves its web UI from the FastAPI backend at `http://127.0.0.1:8000`. The safest remote-access setup is:

1. Keep the app running locally on your machine.
2. Expose it through a Cloudflare Tunnel.
3. Protect the hostname with Cloudflare Access.

That gives you private remote access without opening inbound ports on your network.

## What you need

- A Cloudflare-managed domain or subdomain
- Cloudflare Zero Trust enabled for your account
- `cloudflared` installed on the same machine that runs this app
- A managed tunnel token from Cloudflare

## Optional local config in `backend/.env`

If you want to swap hostnames or tokens without editing your PowerShell command each time, set these in `backend/.env`:

```dotenv
CLOUDFLARE_TUNNEL_TOKEN=
CLOUDFLARE_PUBLIC_HOSTNAME=arena.yourdomain.com
CLOUDFLARE_BACKEND_HEALTH_URL=http://127.0.0.1:8000/health
CLOUDFLARE_ACCESS_EMAIL=you@example.com
```

The PowerShell launchers load `backend/.env` automatically now.

## Recommended Cloudflare setup

Use a dashboard-managed tunnel so the local machine only needs a token.

### 1. Create a tunnel

In Cloudflare Zero Trust:

1. Go to `Networks` -> `Tunnels`
2. Create a new `Cloudflared` tunnel
3. Name it something like `polymarket-arena`
4. Copy the tunnel token

### 2. Add a public hostname

Inside the tunnel configuration, add a public hostname such as:

- `arena.yourdomain.com`

Point it to this local service:

- Type: `HTTP`
- URL: `http://127.0.0.1:8000`

### 3. Protect it with Access

In Cloudflare Zero Trust:

1. Go to `Access` -> `Applications`
2. Add a `Self-hosted` application
3. Use the same hostname, for example `arena.yourdomain.com`
4. Add an allow policy for only the identities you trust

Good starter policy:

- Allow your email address only

If you want the fastest setup, use:

- One-time PIN to your email

If you already use Google, GitHub, or another IdP in Access, use that instead.

## Local usage

### Option A: Start backend and tunnel separately

Terminal 1:

```powershell
.\scripts\run-backend.ps1
```

Terminal 2:

```powershell
.\scripts\run-cloudflare-tunnel.ps1
```

The tunnel script first tries `cloudflared` on `PATH`, then falls back to common Windows install locations such as the default winget path.

### Option B: Launch both together

```powershell
.\scripts\run-remote-ui.ps1
```

That script starts the backend in a separate PowerShell window, waits for `http://127.0.0.1:8000/health`, and then starts the tunnel.

## Notes

- The tunnel script checks that the backend is healthy before it starts, unless you pass `-SkipBackendCheck`.
- The app stays local-first. Cloudflare only proxies requests to your local machine.
- Keep this admin UI private. It can switch modes, submit orders, and award capital.
- `CLOUDFLARE_TUNNEL_TOKEN` is sensitive. `backend/.env` should stay local and uncommitted.
- `CLOUDFLARE_PUBLIC_HOSTNAME` is just a local reference for the scripts and docs. If you switch to a different real domain, you still need to update the Cloudflare tunnel route and Access app in the dashboard.

## Example commands

Run the tunnel when the backend is already up:

```powershell
.\scripts\run-cloudflare-tunnel.ps1
```

Use a custom `cloudflared` path:

```powershell
.\scripts\run-cloudflare-tunnel.ps1 -CloudflaredPath 'C:\Program Files\cloudflared\cloudflared.exe'
```
