from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from skillanything.pipeline import SkillAnythingApp  # noqa: E402

PROFILE_ID = "d4f261b35690b713d0d721147a5ba599"
BATCH_SIZE = int(os.getenv("SKILLANYTHING_IMAGE_BATCH_SIZE", "80"))
WORKERS = int(os.getenv("SKILLANYTHING_IMAGE_WORKERS", "8"))


def main() -> None:
    sa = SkillAnythingApp()
    batch = 0
    while True:
        batch += 1
        started = time.time()
        result = sa.analyze_media(
            profile_id=PROFILE_ID,
            kinds={"image"},
            limit=BATCH_SIZE,
            workers=WORKERS,
        )
        elapsed = time.time() - started
        print(
            {
                "batch": batch,
                "elapsed_seconds": round(elapsed, 1),
                **result.to_dict(),
            },
            flush=True,
        )
        if result.attempted == 0:
            break
        if result.failed and result.analyzed == 0:
            time.sleep(30)


if __name__ == "__main__":
    main()
