# Star City Beetles, Bones & Oddities

Website for Star City Beetles, Bones & Oddities: dermestid beetle cleaning for skulls and specimens in Lincoln, Nebraska.

Static site served by GitHub Pages from the `main` branch root at **https://starcitybeetles.com** (custom domain set by the `CNAME` file; DNS at Squarespace).

## Updating

- **Phone, email, location, prices:** edit the `SITE` block near the bottom of `index.html`. Set a price to a number (e.g. `85`) to show "$85 / starting at"; leave it `null` to show "Call For".
- **Photos:** replace files in `images/` and keep the same names (`mount-1.jpg` … `mount-10.jpg`). Resize to ~1600px on the long side first.
- **Logo:** `images/logo.png` (nav) and `images/logo-silver.png` (hero stamp).
- **Share image:** `images/og.jpg` (1200×630).

Site by [ITW Web Co.](https://imthewilbur.com)

## For Sale shelf (self-serve)

Tony lists items with a Tally form → Make.com → GitHub Action → live site, no code edits.

- **Data:** `shelf.json` (items, prices, status). Photos live in `images/shelf/` (`NNN-1.jpg` full size, `NNN-1-sm.jpg` card size).
- **Engine:** `.github/workflows/shelf-update.yml` runs `scripts/shelf_update.py` on each `shelf-submission` dispatch. It checks the shop code (repo secret `SHELF_CODE`), downloads and resizes photos, updates `shelf.json`, and commits.
- **Actions the form supports:** add a new item, mark an item SOLD (by `#number` or name), remove an item. Item numbers are never reused.
- **Manual run / fix:** Actions tab → *Shelf update* → *Run workflow* with a payload such as `{"action":"sold","code":"<shop code>","item":"#3"}`. You can also edit `shelf.json` directly.
- **If a submission fails** (wrong code, unknown item, bad photo), the run shows red in the Actions tab with the reason, and GitHub emails the repo owner.
