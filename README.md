# OX Trails — Routes

An interactive off-road cycling routes section for [oxtrails.org.uk](https://www.oxtrails.org.uk/), built as a single self-contained page.

- **Interactive map** (Leaflet + OpenStreetMap / CyclOSM) with each route drawn on it
- **Route list** with descriptions and route notes
- **GPX download** per route
- **Geotagged photos** shown as pins along the route, with a full-screen viewer

Live site (GitHub Pages): https://daniel-stone.github.io/oxtrails-routes/

## Structure

- `index.html` — the whole widget (HTML/CSS/JS in one file). Leaflet, fonts and map tiles load from CDNs.
- `photos/` — web-optimised route photos and thumbnails.

## Adding a route

Edit the `ROUTES` array in `index.html`. Each route is an object with a name, type (`circular` / `ptp`), distance (in km — displayed in miles), a `track` array of `[lat, lon]` points, and optional `ele`, `photos`, and description fields.

## Deploying to Squarespace

The contents of `index.html` can be pasted into a Squarespace **Code Block**. Photos referenced by the `photos/` paths need to be hosted (e.g. left on GitHub Pages and referenced by full URL, or uploaded to Squarespace).
