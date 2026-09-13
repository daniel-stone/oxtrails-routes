#!/usr/bin/env python3
"""Build the OX Trails routes site.

Reads the folder-per-route structure under routes/ and writes a deployable
site to _site/. Contributors never edit generated files -- everything the page
needs is derived from each route's route.gpx, route.md and photos/.

  python tools/build_routes.py            # build into _site/
  python tools/build_routes.py --check    # validate only, write nothing

--check is what CI runs on pull requests, so a malformed route fails the PR
instead of silently disappearing from the live page.
"""

import argparse
import json
import math
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import markdown
import yaml
from PIL import Image

# --- tunables ---------------------------------------------------------------

# Raw GPS elevation is noisy: summing every positive delta inflates ascent
# badly. Smooth over a few points, then only count climbs that clear the
# threshold. The result is an estimate and will not match Strava exactly --
# every tool smooths differently. Pin `ascent:` in route.md to override.
ASCENT_SMOOTH_WINDOW = 5
ASCENT_THRESHOLD_M = 1.0

# Douglas-Peucker tolerance for the on-screen track. The .gpx served for
# download is always the contributor's original file, untouched.
SIMPLIFY_TOLERANCE_M = 5.0

THUMB_MAX_PX = 160
THUMB_QUALITY = 72

VALID_TYPES = ("circular", "ptp")
REQUIRED_FIELDS = ("name", "type", "start", "surface")
PHOTO_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")

NOTES_HEADING = re.compile(r"^##\s+route notes\s*$", re.IGNORECASE | re.MULTILINE)


class RouteError(Exception):
    """A problem with one route folder, reported with the folder name."""


# --- geometry ---------------------------------------------------------------


def haversine_m(a, b):
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(h))


def track_distance_km(segments):
    """Distance along each segment.

    The gap between one segment and the next was never ridden, so it must not
    be measured. Joining them added 289km to a 10.8km file.
    """
    metres = 0.0
    for points in segments:
        metres += sum(haversine_m(points[i - 1], points[i]) for i in range(1, len(points)))
    return metres / 1000.0


def track_ascent_m(segments):
    """Total climb across every segment.

    Per segment, so neither the smoothing window nor the accumulator reads a
    step between two unconnected pieces as a hill.
    """
    climbs = [c for c in (_segment_ascent_m(p) for p in segments) if c is not None]
    return round(sum(climbs)) if climbs else None


def _segment_ascent_m(points):
    """Estimated climb for one segment: smooth the trace, then accumulate.

    The reference height only moves when the track has genuinely gone that far
    up or down, so sensor noise on a flat towpath contributes nothing.
    """
    eles = [p[2] for p in points if p[2] is not None]
    if len(eles) < 2:
        return None

    half = ASCENT_SMOOTH_WINDOW // 2
    smoothed = [
        sum(eles[max(0, i - half):i + half + 1]) / len(eles[max(0, i - half):i + half + 1])
        for i in range(len(eles))
    ]

    ascent = 0.0
    ref = smoothed[0]
    for e in smoothed[1:]:
        if e >= ref + ASCENT_THRESHOLD_M:
            ascent += e - ref
            ref = e
        elif e <= ref - ASCENT_THRESHOLD_M:
            ref = e
    return round(ascent)


def simplify(points, tolerance_m=SIMPLIFY_TOLERANCE_M):
    """Douglas-Peucker, iterative so a 30k-point track can't blow the stack."""
    n = len(points)
    if n < 3:
        return list(points)

    # Local flat-earth projection: fine over a single route's extent.
    kx = 111320.0 * math.cos(math.radians(points[0][0]))
    ky = 110540.0
    xy = [(p[1] * kx, p[0] * ky) for p in points]

    keep = [False] * n
    keep[0] = keep[n - 1] = True
    stack = [(0, n - 1)]
    tol2 = tolerance_m * tolerance_m

    while stack:
        first, last = stack.pop()
        if last <= first + 1:
            continue
        ax, ay = xy[first]
        bx, by = xy[last]
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        worst, worst_i = -1.0, -1
        for i in range(first + 1, last):
            px, py = xy[i]
            if seg2 == 0:
                d2 = (px - ax) ** 2 + (py - ay) ** 2
            else:
                t = ((px - ax) * dx + (py - ay) * dy) / seg2
                t = 0.0 if t < 0 else (1.0 if t > 1 else t)
                d2 = (px - (ax + t * dx)) ** 2 + (py - (ay + t * dy)) ** 2
            if d2 > worst:
                worst, worst_i = d2, i
        if worst > tol2:
            keep[worst_i] = True
            stack.append((first, worst_i))
            stack.append((worst_i, last))

    return [points[i] for i in range(n) if keep[i]]


# --- parsing ----------------------------------------------------------------


def parse_gpx(path):
    """Track points grouped by <trkseg>, namespace-agnostic.

    Segment boundaries carry meaning: a GPX may hold unconnected pieces, and
    running them together invents both distance and a line on the map that
    nobody can ride.
    """
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        raise RouteError(f"route.gpx is not valid XML: {exc}") from exc

    segments = []
    current = None
    for el in tree.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "trkseg":
            current = []
            segments.append(current)
            continue
        if tag != "trkpt":
            continue
        lat, lon = el.get("lat"), el.get("lon")
        if lat is None or lon is None:
            continue
        ele = None
        for child in el:
            if child.tag.rsplit("}", 1)[-1] == "ele" and (child.text or "").strip():
                try:
                    ele = float(child.text.strip())
                except ValueError:
                    ele = None
        try:
            point = (float(lat), float(lon), ele)
        except ValueError:
            raise RouteError(f"route.gpx has a track point with non-numeric coordinates: {lat},{lon}")
        if current is None:          # a trkpt sitting outside any trkseg
            current = []
            segments.append(current)
        current.append(point)

    # A lone point draws nothing and measures nothing. Drop it rather than
    # reject a file that is otherwise fine.
    segments = [s for s in segments if len(s) >= 2]
    if not segments:
        raise RouteError("route.gpx has no track segment with two or more points")
    return segments


def parse_front_matter(path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise RouteError("route.md must start with a --- front matter block")
    end = text.find("\n---", 3)
    if end == -1:
        raise RouteError("route.md front matter is never closed with ---")

    raw = text[3:end]
    body = text[end + 4:].lstrip("\r\n")
    try:
        meta = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise RouteError(f"route.md front matter is not valid YAML: {exc}") from exc
    if not isinstance(meta, dict):
        raise RouteError("route.md front matter must be a set of key: value pairs")
    return meta, body


def split_body(body):
    """Prose before '## Route notes' is the description, the rest is notes."""
    match = NOTES_HEADING.search(body)
    if not match:
        return md(body), ""
    return md(body[: match.start()]), md(body[match.end():])


def md(text):
    text = text.strip()
    return markdown.markdown(text) if text else ""


# --- photos -----------------------------------------------------------------


def _dms_to_deg(value):
    degrees, minutes, seconds = (float(v) for v in value)
    return degrees + minutes / 60.0 + seconds / 3600.0


def exif_latlon(path):
    """GPS coordinates from EXIF, or None if the tags aren't there.

    Most web-optimisers strip EXIF entirely, which is why front matter has to
    stay a supported way of supplying coordinates.
    """
    try:
        with Image.open(path) as im:
            gps = im.getexif().get_ifd(0x8825)
    except Exception:
        return None
    if not gps:
        return None
    try:
        lat = _dms_to_deg(gps[2])
        lon = _dms_to_deg(gps[4])
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    if str(gps.get(1, "N")).upper().startswith("S"):
        lat = -lat
    if str(gps.get(3, "E")).upper().startswith("W"):
        lon = -lon
    return lat, lon


def collect_photos(route_dir, meta):
    """Photos sorted by filename, each needing coordinates from EXIF or YAML."""
    declared = {}
    for entry in meta.get("photos") or []:
        if not isinstance(entry, dict) or "file" not in entry:
            raise RouteError("each photos: entry needs at least a 'file:' key")
        declared[str(entry["file"])] = entry

    photo_dir = route_dir / "photos"
    if not photo_dir.is_dir():
        if declared:
            raise RouteError("route.md has a photos: list but there is no photos/ folder")
        return []

    files = sorted(
        (p for p in photo_dir.iterdir() if p.suffix.lower() in PHOTO_SUFFIXES and p.is_file()),
        key=lambda p: p.name.lower(),
    )

    unknown = set(declared) - {p.name for p in files}
    if unknown:
        raise RouteError(
            "route.md lists photos that aren't in photos/: " + ", ".join(sorted(unknown))
        )

    photos = []
    for path in files:
        entry = declared.get(path.name, {})
        coords = exif_latlon(path)
        if entry.get("lat") is not None and entry.get("lon") is not None:
            coords = (float(entry["lat"]), float(entry["lon"]))
        if coords is None:
            raise RouteError(
                f"photos/{path.name} has no GPS EXIF and no lat/lon in route.md.\n"
                f"    Most photo compressors strip EXIF. Either commit the original "
                f"file from your phone, or add to the photos: list in route.md:\n"
                f"      - file: {path.name}\n"
                f"        lat: 51.7\n"
                f"        lon: -1.2"
            )
        photos.append(
            {
                "src": f"photos/{path.name}",
                "thumb": f"photos/thumbs/{path.name}",
                "lat": round(coords[0], 6),
                "lon": round(coords[1], 6),
                "caption": str(entry.get("caption", "")),
                "_path": path,
            }
        )
    return photos


def write_thumb(src, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail((THUMB_MAX_PX, THUMB_MAX_PX), Image.LANCZOS)
        im.save(dest, "JPEG", quality=THUMB_QUALITY, optimize=True)


# --- route assembly ---------------------------------------------------------


def load_route(route_dir):
    gpx_path = route_dir / "route.gpx"
    if not gpx_path.exists():
        raise RouteError("no route.gpx in this folder")

    meta, body = parse_front_matter(route_dir / "route.md")

    missing = [f for f in REQUIRED_FIELDS if not str(meta.get(f, "")).strip()]
    if missing:
        raise RouteError("route.md is missing required field(s): " + ", ".join(missing))
    if meta["type"] not in VALID_TYPES:
        raise RouteError(f"type: must be one of {' or '.join(VALID_TYPES)}, not '{meta['type']}'")

    segments = parse_gpx(gpx_path)
    desc_html, notes_html = split_body(body)
    photos = collect_photos(route_dir, meta)

    distance = meta.get("distance")
    distance_km = float(distance) if distance is not None else round(track_distance_km(segments), 1)

    ascent = meta.get("ascent")
    ascent_m = int(ascent) if ascent is not None else track_ascent_m(segments)

    time_hrs = meta.get("timeHrs")

    drawn = [simplify(seg) for seg in segments]

    return {
        "id": route_dir.name,
        "name": str(meta["name"]),
        "type": meta["type"],
        "start": str(meta["start"]),
        "surface": str(meta["surface"]),
        "distanceKm": round(distance_km, 1),
        "ascentM": ascent_m,
        "timeHrs": float(time_hrs) if time_hrs is not None else None,
        "order": int(meta["order"]) if meta.get("order") is not None else None,
        "descHtml": desc_html,
        "notesHtml": notes_html,
        "gpx": "route.gpx",
        "segments": [[[round(p[0], 6), round(p[1], 6)] for p in seg] for seg in drawn],
        # Deprecated flattened copy. The page markup is also pasted into
        # Squarespace, which updates on its own schedule, so a copy still
        # running the pre-segment script keeps working off this. Drop it
        # once those embeds have been refreshed.
        "track": [[round(p[0], 6), round(p[1], 6)] for seg in drawn for p in seg],
        "photos": photos,
        "_dir": route_dir,
        "_rawPoints": sum(len(seg) for seg in segments),
        "_segments": len(segments),
    }


def summarise(route):
    return {
        "id": route["id"],
        "name": route["name"],
        "type": route["type"],
        "distanceKm": route["distanceKm"],
        "ascentM": route["ascentM"],
        "timeHrs": route["timeHrs"],
        "photoCount": len(route["photos"]),
    }


def sort_key(route):
    # Explicit order first, then everything else alphabetically behind it.
    return (route["order"] if route["order"] is not None else 9999, route["name"].lower())


# --- output -----------------------------------------------------------------


def write_site(routes, root, out):
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    shutil.copy2(root / "index.html", out / "index.html")
    nojekyll = root / ".nojekyll"
    if nojekyll.exists():
        shutil.copy2(nojekyll, out / ".nojekyll")

    for route in routes:
        dest = out / "routes" / route["id"]
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(route["_dir"] / "route.gpx", dest / "route.gpx")

        for photo in route["photos"]:
            src = photo.pop("_path")
            (dest / photo["src"]).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / photo["src"])
            write_thumb(src, dest / photo["thumb"])

        payload = {k: v for k, v in route.items() if not k.startswith("_")}
        (dest / "route.json").write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )

    index = {"routes": [summarise(r) for r in routes]}
    (out / "routes" / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate only, write nothing")
    parser.add_argument("--out", default="_site", help="output directory (default: _site)")
    parser.add_argument("--root", default=".", help="repository root (default: .)")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    routes_dir = root / "routes"
    if not routes_dir.is_dir():
        print(f"error: no routes/ directory in {root}", file=sys.stderr)
        return 1

    folders = sorted(p for p in routes_dir.iterdir() if p.is_dir() and (p / "route.md").exists())
    stray = sorted(
        p.name for p in routes_dir.iterdir() if p.is_dir() and not (p / "route.md").exists()
    )
    if not folders:
        print("error: no route folders found under routes/", file=sys.stderr)
        return 1

    routes, errors = [], []
    for folder in folders:
        try:
            routes.append(load_route(folder))
        except RouteError as exc:
            errors.append(f"routes/{folder.name}: {exc}")
        except Exception as exc:  # noqa: BLE001 - surface the folder, not a bare traceback
            errors.append(f"routes/{folder.name}: unexpected {type(exc).__name__}: {exc}")

    for name in stray:
        errors.append(f"routes/{name}: folder has no route.md, so it would not appear on the site")

    duplicates = {r["name"] for r in routes if [x["name"] for x in routes].count(r["name"]) > 1}
    for name in sorted(duplicates):
        errors.append(f"two route folders share the name '{name}'")

    if errors:
        print(f"\n{len(errors)} problem(s) found:\n", file=sys.stderr)
        for err in errors:
            print(f"  x {err}", file=sys.stderr)
        print("", file=sys.stderr)
        return 1

    routes.sort(key=sort_key)

    for route in routes:
        ascent = f"{route['ascentM']}m" if route["ascentM"] is not None else "no elevation data"
        print(
            f"  ok {route['id']}: {route['distanceKm']}km, {ascent}, "
            f"{route['_rawPoints']} pts -> {len(route['track'])} drawn, "
            f"{route['_segments']} segment(s), "
            f"{len(route['photos'])} photo(s)"
        )

    if args.check:
        print(f"\n{len(routes)} route(s) valid.")
        return 0

    write_site(routes, root, Path(args.out).resolve())
    print(f"\nBuilt {len(routes)} route(s) into {args.out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
