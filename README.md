# Quantum-Safe Kadena

Source for the static explainer at [quantum.kadena.ws](https://quantum.kadena.ws). The page describes Kadena's post-quantum account format and reads its progress, GitHub facts, and mainnet fork state from same-origin JSON files.

## Files

| File | Purpose |
| --- | --- |
| `index.html` | Complete explainer page, styles, and client-side rendering. |
| `nexus-mark.png` | Kadena Nexus mark used in the shared product header and as the favicon. |
| `nexus-mark-64.png` | The same mark at 64×55, served in the page header so phones download a small image. |
| `assessment.json` | Milestone weights, initial scores, and rules for automatic score increases. |
| `status.json` | Bootstrap snapshot of GitHub and mainnet facts; refreshed by the updater. |
| `update_status.py` | Standard-library Python job that refreshes `status.json` and raises milestone scores in `assessment.json` when evidence changes. |
| `DEPLOY.md` | Nginx, cron, and deployment instructions. |

The page follows the [Kadena Nexus header standard](https://github.com/KadenaNexus/homepage/blob/main/docs/brand/HEADER-STANDARD.md): shared mark, full product name, “Part of Kadena Nexus” links, and branded browser title.

## Local preview

Serve this directory with any static HTTP server. For example:

```sh
python3 -m http.server 8000
```

Open `http://localhost:8000`. The page uses `fetch()` for `assessment.json` and `status.json`, so it should be served over HTTP rather than opened as a local file.

## Progress data

The hourly updater reads public GitHub data and the configured Kadena mainnet node. It writes live facts to `status.json` and only raises automatic milestone scores in `assessment.json`. If a lookup fails, the last available fork value and milestone scores remain in place. No API token is required for normal operation; any optional GitHub token must be read-only.

The progress measure is an educational status snapshot, not an official Kadena roadmap or a security guarantee. See the page for sources and scope.

## Deployment

Follow [DEPLOY.md](DEPLOY.md). Changes to the static page and Nexus mark take effect as soon as the files are copied; the updater, JSON state, and hourly cron remain independent. Preserve the production `assessment.json` and `status.json` during ordinary page deployments so the live scores and timestamps are retained.

Commit changes through pull requests and tag each production deployment.
