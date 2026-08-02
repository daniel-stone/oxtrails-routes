# Adding a route

A route is a folder. Add the folder, open a pull request — you never need to
touch `index.html` or any shared file, so two people can add routes at the same
time without conflicting.

```
routes/
  your-route-name/
    route.gpx          # required
    route.md           # required
    photos/            # optional
      01-first-view.jpg
      02-the-big-climb.jpg
```

The folder name becomes the route's id, so use lower-case-with-hyphens.

## 1. The GPX file

Export from Garmin, Strava, Komoot, RideWithGPS or whatever you use, and save
it as `route.gpx`. Don't simplify or clean it up — the page draws a simplified
copy but always offers your original file for download.

Distance and total climb are calculated from this file, so you don't enter them
by hand.

## 2. `route.md`

```markdown
---
name: Wittenham Clumps Loop
type: circular              # circular or ptp (point-to-point)
start: Dorchester-on-Thames village car park
surface: Bridleway, gravel and a little tarmac
order: 4                    # optional: where it sits in the list
timeHrs: 2.5                # optional: a realistic riding time
photos:                     # optional, see below
  - file: 01-first-view.jpg
    caption: Looking north from the Clumps
---

A short loop over the **Clumps** with a proper view at the top. Opening
paragraphs like this one are the description shown under the route name.

## Route notes

Anything after a "Route notes" heading becomes the notes section: surface
warnings, where to get water, which gate is always jammed.
```

`name`, `type`, `start` and `surface` are required; everything else is
optional. Markdown formatting (`**bold**`, links, bullet lists) works in the
body.

### Overriding calculated values

Add `distance:` (km) or `ascent:` (metres) to the front matter only when the
calculated figure is wrong — for instance when the GPX has been downsampled or
has no elevation data. Anything you pin wins over the calculation.

## 3. Photos (optional)

Drop them in `photos/`. They're shown as pins along the route, ordered by
filename, so name them `01-`, `02-` and so on. Thumbnails are generated for
you — don't commit your own.

**Photos need coordinates.** Straight from a phone, they usually have GPS
EXIF and there's nothing to do but add a caption. But most photo compressors
and "save for web" tools strip EXIF, and then the build can't place the pin.
If that happens the build tells you which file is affected, and you add the
position by hand:

```yaml
photos:
  - file: 02-the-big-climb.jpg
    caption: Halfway up, looking back
    lat: 51.6234
    lon: -1.1902
```

Coordinates are public once published, which is the point — but it does mean
you shouldn't add photos taken somewhere you'd rather not pin on a map.

## 4. Check it before you push

```bash
pip install -r tools/requirements.txt
python tools/build_routes.py --check
```

That's exactly what runs on your pull request. It reports every problem it
finds at once, naming the folder and the fix.

To see the real page locally:

```bash
python tools/build_routes.py && python -m http.server -d _site 8000
```

Then open <http://localhost:8000>. The page fetches its data, so opening
`index.html` directly from disk will not work.
