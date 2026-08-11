"""Paint out the leaked phone number in the two Rina group-chat creatives.

The WhatsApp screenshots used by F's 医生说不会再长 ad and by card 4 of C's best-of carousel were
cropped mid-header, leaving a member's mobile number visible along the top edge of two chat
blocks — dim grey on a dark bubble, easy to miss, but a real person's number. Operator rule: an
image showing a phone number must not run.

Rather than a black bar (which reads as "something was hidden here"), each region is filled with
the median tone of that bubble's own dark background sampled just below it, so the strip looks
like ordinary empty bubble padding.

Two details make the fill safe rather than blunt:
  · only pixels darker than lum 178 are replaced, so the white separator bars between screenshots
    survive instead of being punched through;
  · the right edge is clamped to where the dark screenshot actually ends on those rows, so the
    fill never spills onto the card's orange background or Martin's cutout.

Regions were located from the row luminance profile: the message text is bright white (>190)
while the leaked number is dim grey (70–175), so the number's rows are the ones carrying dim
glyphs and no bright text. Re-run after re-exporting either source image; it is idempotent
(filling an already-filled region is a no-op).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets" / "sg_batch"

# (relative asset path, [(x0, y0, x1, y1), ...]) — boxes in the 1200×1200 source coordinates
TARGETS = [
    (ASSETS / "f_backup" / "doctor_said_no" / "img.jpg",
     [(700, 744, 1015, 778), (700, 924, 1015, 940)]),
    (ASSETS / "c_proof" / "review_best_of" / "card_04.jpg",
     [(700, 680, 1015, 710), (700, 852, 1015, 884)]),
]


def redact(path: Path, boxes) -> list[str]:
    im = Image.open(path).convert("RGB")
    a = np.asarray(im).astype(np.uint8).copy()
    notes = []
    for (x0, y0, x1, y1) in boxes:
        band = a[y0:y1, x0:x1].mean(axis=2)
        dark_cols = (band < 120).mean(axis=0) > 0.45
        idx = np.where(dark_cols)[0]
        if len(idx) == 0:
            notes.append(f"y{y0}-{y1}: no dark columns — skipped (source layout changed?)")
            continue
        xr = x0 + int(idx.max()) + 1                     # clamp to the screenshot's right edge
        sample = a[y1 + 3:y1 + 16, x0:xr].reshape(-1, 3)
        dark = sample[sample.mean(axis=1) < 70]
        bg = np.median(dark if len(dark) > 40 else sample, axis=0).astype(np.uint8)
        region = a[y0:y1, x0:xr]
        region[region.mean(axis=2) < 178] = bg           # spare the white separator bars
        a[y0:y1, x0:xr] = region
        notes.append(f"y{y0}-{y1}: filled x{x0}..{xr} with rgb{tuple(int(v) for v in bg)}")
    Image.fromarray(a).save(path, quality=95)
    return notes


def main() -> None:
    for path, boxes in TARGETS:
        if not path.exists():
            print(f"!! missing {path}")
            continue
        print(path.relative_to(ROOT))
        for note in redact(path, boxes):
            print(f"   {note}")


if __name__ == "__main__":
    main()
