# mistral-app — chat with mistral-small-latest

A Mistral App: TanStack Start frontend + FastAPI backend. The chat page lives at `/chat`
(`apps/web/src/routes/chat.tsx`) and posts to `POST /api/chat`
(`apps/api/src/api/routers/api/chat/route.py`), which calls the Mistral API with
`mistral-small-latest` through `caller_mistral_client()`. The API key never reaches the
browser: the platform gateway attaches a short-lived caller token server-side, and locally
`MISTRAL_API_KEY` stays in the gitignored `.env`.

## Run locally

```bash
mistral login                 # one-time browser sign-in
mistral apps install          # restore dependencies after a fresh clone
mistral dev --no-open         # starts the api and web modules plus the local gateway
```

Then open the web module's URL (port 3001 by default). API calls through the local gateway
use your `mistral login` session or a `MISTRAL_API_KEY` exported in the shell.

## Tests

```bash
bash tools/uv.sh run --with pytest python -m pytest apps/api/tests -q
bunx nx run web:test
```

## Deploy to your Mistral App environment

Deployment builds the commit pushed to the repo's `origin` remote, so push first:

```bash
git push -u origin main   # origin = github.com/LArchiviste42/ZPS
# optional mirror to GitLab:
# git remote add gitlab https://gitlab.com/LeGrosChatonFat/mistral-app.git && git push gitlab main
mistral deploy --organization <your-org> --json   # add --workspace <ws> if several exist
```

Then verify with `mistral_mcp_list_apps` / `get_app` and follow the run with
`list_app_deploy_runs`. Any value the app needs in production (e.g. its own
`MISTRAL_API_KEY` if you want it to act as itself instead of per-caller) is set in the
app's Studio settings or Secrets Manager, never in the repo.
