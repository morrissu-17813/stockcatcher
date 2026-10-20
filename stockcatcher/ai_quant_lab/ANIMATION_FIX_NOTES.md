# Agent Motion Fix

This patch improves the preview.html interface that is served at `/` by `server.py`.

- The earlier preview used one still PNG per dog and only applied a tiny left/right transform. The filenames ending in `-sprite.png` were not animated sprite sheets.
- The preview now cycles through distinct scene states: observe, travel to a workstation, report, return, sit, and stand. Travel includes a horizontal route and vertical gait-like bounce, not only a rocking transform.
- Runtime warning and success statuses keep priority over ambient choreography.
- These are CSS choreography effects over the existing still illustrations; they do not yet have true frame-by-frame leg articulation. For that, each character needs a cleaned, consistent animation sprite sequence.
- No Tianji 3K or TIDE Dashboard production files were modified. Paper-trading and persistence logic are unchanged.
