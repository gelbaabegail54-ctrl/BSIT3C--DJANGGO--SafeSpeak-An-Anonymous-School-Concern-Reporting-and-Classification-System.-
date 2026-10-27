"""Validation helpers for images attached to anonymous reports."""

import uuid

MAX_REPORT_IMAGES = 3
MAX_REPORT_IMAGE_BYTES = 5 * 1024 * 1024

PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
ALLOWED_IMAGE_TYPES = ('jpg', 'png', 'webp')
IMAGE_TYPE_LABELS = 'JPG, PNG, or WebP'


def detect_image_type(uploaded_file):
    """Return the image format based on the file signature, or None."""
    uploaded_file.seek(0)
    header = uploaded_file.read(16)
    uploaded_file.seek(0)

    if header.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    if header.startswith(PNG_SIGNATURE):
        return 'png'
    if header[:4] == b'RIFF' and header[8:12] == b'WEBP':
        return 'webp'
    return None


def prepare_report_images(files):
    """Validate uploads and return ``(prepared_files, errors)``.

    Accepted files are renamed to random identifiers so the original filename
    cannot reveal information about the reporter. The extension is derived from
    the detected file signature rather than the submitted name.
    """
    files = [uploaded for uploaded in files if uploaded and uploaded.name]
    errors = []

    if len(files) > MAX_REPORT_IMAGES:
        return [], [f'You can attach up to {MAX_REPORT_IMAGES} images per report.']

    prepared = []
    for uploaded in files:
        label = uploaded.name

        if uploaded.size == 0:
            errors.append(f'"{label}" is empty. Choose another image.')
            continue

        if uploaded.size > MAX_REPORT_IMAGE_BYTES:
            limit_mb = MAX_REPORT_IMAGE_BYTES // (1024 * 1024)
            errors.append(f'"{label}" is larger than {limit_mb} MB.')
            continue

        image_type = detect_image_type(uploaded)
        if image_type is None:
            errors.append(
                f'"{label}" is not a supported image. Use {IMAGE_TYPE_LABELS}.'
            )
            continue

        uploaded.name = f'{uuid.uuid4().hex}.{image_type}'
        prepared.append(uploaded)

    return prepared, errors
