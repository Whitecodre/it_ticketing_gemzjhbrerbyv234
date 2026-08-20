import subprocess
import os
import tempfile
import logging
import requests
from django.core.files import File
from django.conf import settings

logger = logging.getLogger(__name__)


def _local_path_for(field_file):
    """Returns a local filesystem path for a Django FieldFile, regardless of
    storage backend: the field's own `.path` in dev (FileSystemStorage), or
    a downloaded temp copy in production (Cloudinary/other remote storage,
    whose `.path` raises NotImplementedError). Mirrors the same fallback
    already used for DOCX exports in apps/tickets/report_exporters.py's
    _docx_image_source(). Returns (path, is_temp) so callers know whether to
    clean the file up themselves."""
    try:
        return field_file.path, False
    except NotImplementedError:
        pass

    suffix = os.path.splitext(field_file.name)[1]
    resp = requests.get(field_file.url, timeout=30)
    resp.raise_for_status()
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(resp.content)
    finally:
        tmp.close()
    return tmp.name, True

def convert_office_to_pdf(input_file_path, output_dir=None):
    """
    Convert an Office document (DOC, DOCX, XLS, XLSX, PPT, PPTX) to PDF
    using LibreOffice headless mode.
    Returns the path to the generated PDF, or None on failure.
    """
    if not os.path.exists(input_file_path):
        logger.error(f"Input file not found: {input_file_path}")
        return None

    # Create a temporary directory for output if not provided. Only clean
    # this up ourselves on a *failure* path below - on success, the
    # returned PDF lives inside it, so the caller (generate_preview_for_
    # document) is responsible for removing it once it's done reading the
    # file. A blanket `finally: shutil.rmtree(output_dir)` here used to
    # delete the directory - and the PDF we'd just returned a path to -
    # before the caller ever got to open it, silently breaking every
    # conversion regardless of storage backend or OS.
    created_own_dir = output_dir is None
    if created_own_dir:
        output_dir = tempfile.mkdtemp(prefix='libreoffice_')

    def _cleanup_on_failure():
        if created_own_dir:
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)

    try:
        # Run LibreOffice headless conversion.
        #
        # NOTE: a per-call -env:UserInstallation profile was tried here to
        # avoid "already running" lock conflicts under concurrent
        # conversions, but it made every single call pay LibreOffice's slow
        # first-run profile initialization cost (30s-2min+ on Windows,
        # worse under antivirus scanning) instead of reusing a warm,
        # already-initialized default profile - a bad trade for a
        # concurrency edge case that wasn't an observed problem. Reverted;
        # the existing per-document cache lock in views.py's document_viewer
        # already prevents the common case (double-clicking view on the
        # same missing preview).
        binary = getattr(settings, 'LIBREOFFICE_BINARY_PATH', 'soffice')
        cmd = [
            binary,
            '--headless',
            '--convert-to', 'pdf',
            '--outdir', output_dir,
            input_file_path
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120  # allow up to 2 minutes for large files
        )

        if result.returncode != 0:
            logger.error(f"LibreOffice conversion failed: {result.stderr}")
            _cleanup_on_failure()
            return None

        # The output file will be named <input_filename>.pdf
        base_name = os.path.splitext(os.path.basename(input_file_path))[0]
        output_pdf_path = os.path.join(output_dir, f"{base_name}.pdf")
        if not os.path.exists(output_pdf_path):
            logger.error(f"PDF output not found: {output_pdf_path}")
            _cleanup_on_failure()
            return None

        return output_pdf_path

    except subprocess.TimeoutExpired:
        logger.error("LibreOffice conversion timed out (120s)")
        _cleanup_on_failure()
        return None
    except Exception as e:
        logger.error(f"Unexpected conversion error: {e}")
        _cleanup_on_failure()
        return None


def generate_preview_for_document(document):
    """
    Generate a preview PDF for a document's file if it's an Office file.
    Stores the preview in document.preview_pdf.
    Returns True on success, False on failure.
    """
    if not document.file:
        return False

    ext = document.file_extension
    office_extensions = ['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx']
    if ext not in office_extensions:
        # No conversion needed – clear any stale preview
        if document.preview_pdf:
            document.preview_pdf.delete(save=False)
            document.preview_pdf = None
            document.save(update_fields=['preview_pdf'])
        return True  # nothing to do, but we consider it successful

    # Convert the file — fetch it to a local path first, since remote
    # storage (Cloudinary in production) doesn't support `.file.path`.
    input_path, input_is_temp = _local_path_for(document.file)
    try:
        pdf_path = convert_office_to_pdf(input_path)
    finally:
        if input_is_temp:
            try:
                os.remove(input_path)
            except OSError:
                pass

    if pdf_path and os.path.exists(pdf_path):
        # Save the PDF as a Django FileField, then remove convert_office_to_
        # pdf's temp output directory now that we've actually read the file
        # out of it (it deliberately leaves this to us on success - see the
        # comment in convert_office_to_pdf).
        with open(pdf_path, 'rb') as f:
            doc_file = File(f, name=f"{document.slug}_preview.pdf")
            document.preview_pdf.save(
                f"{document.slug}_preview.pdf",
                doc_file,
                save=False
            )
        document.save(update_fields=['preview_pdf'])
        import shutil
        shutil.rmtree(os.path.dirname(pdf_path), ignore_errors=True)
        return True
    else:
        # If conversion fails, clear any existing preview
        if document.preview_pdf:
            document.preview_pdf.delete(save=False)
            document.preview_pdf = None
            document.save(update_fields=['preview_pdf'])
        return False


def get_document_view(request):
    """Get the user's preferred document view."""
    if request.user.is_authenticated and hasattr(request.user, 'profile'):
        return request.user.profile.default_document_view
    return request.session.get('doc_view_mode', 'grid')


def set_document_view(request, view_mode):
    """Set the user's preferred document view."""
    if view_mode not in ['grid', 'list']:
        view_mode = 'grid'
    if request.user.is_authenticated and hasattr(request.user, 'profile'):
        profile = request.user.profile
        profile.default_document_view = view_mode
        profile.save(update_fields=['default_document_view'])
    else:
        request.session['doc_view_mode'] = view_mode