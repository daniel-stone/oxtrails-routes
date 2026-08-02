# OX Trails — Routes

An interactive off-road cycling routes section for [oxtrails.org.uk](https://www.oxtrails.org.uk/).

- **Interactive map** (Leaflet + OpenStreetMap / CyclOSM) with each route drawn on it
- **Route list** with descriptions, route notes, distance, climb and riding time
- **GPX download** per route
- **Geotagged photos** shown as pins along the route, with a full-screen viewer

Live site (GitHub Pages): https://daniel-stone.github.io/oxtrails-routes/

## Structure

- `index.html` — the page itself (HTML/CSS/JS in one file). It contains no route
  data; it fetches what it needs at runtime.
- `routes/<id>/` — one folder per route: `route.gpx`, `route.md`, optional `photos/`.
- `tools/build_routes.py` — turns those folders into the JSON the page fetches.
- `.github/workflows/build-routes.yml` — validates pull requests, builds and
  deploys `main`.

## Adding a route

Add a folder under `routes/`. See [CONTRIBUTING.md](CONTRIBUTING.md) — no code
changes required, and nothing generated is committed.

## Building locally

```bash
pip install -r tools/requirements.txt
python tools/build_routes.py            # writes _site/
python -m http.server -d _site 8000
```

`python tools/build_routes.py --check` validates without writing anything, which
is what CI runs on pull requests.

The page fetches its data, so opening `index.html` from disk won't work — serve
`_site/` as above.

## Deployment

GitHub Pages is served from the Actions workflow, not from a branch, so
`_site/`, `routes/index.json` and thumbnails are never committed. Pushing to
`main` rebuilds and redeploys.

## Deploying to Squarespace

The contents of `index.html` can be pasted into a Squarespace **Code Block**. It
fetches route data from GitHub Pages, so `PAGES_ORIGIN` near the top of the
script must point at the live Pages URL — relative paths would resolve against
squarespace.com. Photos and GPX files are served from Pages too; nothing needs
uploading to Squarespace.
