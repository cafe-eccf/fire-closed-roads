# Carreteras cortadas por incendios (DGT) — auto-updating

Turns the DGT's static PDF of fire-closed roads into a live, hourly-refreshing
webpage — free, no server to maintain.

## How it works
1. `scrape_dgt.py` downloads the DGT PDF and parses each row into
   `data/carreteras.json`.
2. `.github/workflows/update.yml` runs that script every hour via GitHub
   Actions and commits the updated JSON back to the repo.
3. `index.html` is a static page that fetches `data/carreteras.json` and
   renders it, re-checking every hour if left open in a browser.
4. GitHub Pages serves `index.html` for free.

## Deploy it (5 minutes)
1. Create a new **public** GitHub repo and push these files to it
   (public repos get free Actions minutes and free Pages hosting).
2. In the repo, go to **Settings → Actions → General → Workflow permissions**
   and select **"Read and write permissions"** (needed so the Action can
   commit the updated JSON).
3. Go to **Settings → Pages**, set Source to **"Deploy from a branch"**,
   branch `main`, folder `/ (root)`.
4. Go to the **Actions** tab and manually run "Update DGT wildfire road
   closures" once (via **Run workflow**) to generate the first real dataset.
5. Your page will be live at `https://<your-username>.github.io/<repo-name>/`
   and will refresh itself every hour after that, automatically.

## Notes / limitations
- The parser is regex-based and anchored on patterns that hold across the
  current PDF (road codes like `A-475`, PK numbers, the `SENTIDO` and
  `NIVEL` enums). If DGT changes the PDF's layout or wording, the parser may
  need small tweaks — check `unparsed_lines` in the output JSON, which
  logs any row it couldn't confidently parse instead of silently dropping it.
- This is not an official DGT channel. Treat it as a convenience layer over
  their real data — the page links back to the source PDF and to 011 /
  nap.dgt.es for anything safety-critical.
- Cron schedule is 5 min past the hour (UTC) — adjust in `update.yml` if you
  want a different cadence (DGT itself may not regenerate the PDF that often
  during an active event, so hourly is already generous).
