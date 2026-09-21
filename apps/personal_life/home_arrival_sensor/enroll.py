from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np

from .config import BASE_DIR, get_settings
from .face_verifier import create_embedding_from_images


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the local owner face embedding for the entrance sensor.")
    parser.add_argument("--images", type=Path, default=BASE_DIR / "data" / "owner_images", help="Folder containing 3-10 owner-only photos.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    image_paths = [path for path in args.images.iterdir() if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}] if args.images.exists() else []
    if not image_paths:
        raise SystemExit(f"No enrollment images found in {args.images}")
    settings = get_settings()
    embedding = create_embedding_from_images(image_paths, settings)
    settings.owner_embedding_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(settings.owner_embedding_path, embedding)
    logging.info("Saved local owner embedding from %s image(s): %s", len(image_paths), settings.owner_embedding_path)


if __name__ == "__main__":
    main()
