import logging
import os

logger = logging.getLogger(__name__)


def _auto_download_enabled() -> bool:
    return os.getenv("SKIN_LESION_AUTO_DOWNLOAD", "true").lower() in ("1", "true", "yes", "on")


def download_model_checkpoint(gdrive_file_id, output_path):
    """
    Download model checkpoint from Google Drive if it doesn't exist.

    Args:
        gdrive_file_id (str): Google Drive file ID
        output_path (str): Path where model will be saved
    """
    if os.path.exists(output_path):
        return

    # Google Drive is unreachable from some networks, where gdown blocks for a
    # long time before failing. Set SKIN_LESION_AUTO_DOWNLOAD=false to fail fast
    # and place the checkpoint at output_path manually instead.
    if not _auto_download_enabled():
        raise FileNotFoundError(
            f"Skin lesion checkpoint missing at {output_path} and "
            "SKIN_LESION_AUTO_DOWNLOAD is disabled; place the file manually."
        )

    import gdown

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    logger.info("Downloading skin lesion checkpoint to %s ...", output_path)
    url = f'https://drive.google.com/uc?id={gdrive_file_id}'
    gdown.download(url, output_path, quiet=False)
    if not os.path.exists(output_path):
        raise FileNotFoundError(f"Skin lesion checkpoint download failed: {output_path}")
    logger.info("Download complete.")

# Usage in app.py
# download_model_checkpoint('your_gdrive_file_id', 'path/to/checkpoint.pth')
