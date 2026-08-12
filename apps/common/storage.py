# apps/common/storage.py
from django.conf import settings


def raw_file_storage():
    """Storage for FileFields holding arbitrary (non-image) uploads —
    documents, ticket attachments, etc. In production, DEFAULT_FILE_STORAGE
    is Cloudinary's MediaCloudinaryStorage, whose default RESOURCE_TYPE is
    'image'; uploading a PDF/DOCX/ZIP under that resource type is wrong and
    was the actual cause of Cloudinary rejecting/mishandling document
    uploads. Returning None here (Django's FileField default) leaves local
    development on its own default storage (plain FileSystemStorage, no
    Cloudinary configured) exactly as before."""
    if settings.DEFAULT_FILE_STORAGE == 'cloudinary_storage.storage.MediaCloudinaryStorage':
        from cloudinary_storage.storage import RawMediaCloudinaryStorage
        return RawMediaCloudinaryStorage()
    return None
