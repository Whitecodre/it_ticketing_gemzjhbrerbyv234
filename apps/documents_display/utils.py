import subprocess
import os
import tempfile
import logging
from django.core.files import File
from django.conf import settings

logger = logging.getLogger(__name__)

def convert_office_to_pdf(input_file_path, output_dir=None):
    """
    Convert an Office document (DOC, DOCX, XLS, XLSX, PPT, PPTX) to PDF
    using LibreOffice headless mode.
    Returns the path to the generated PDF, or None on failure.
    """
    if not os.path.exists(input_file_path):
        logger.error(f"Input file not found: {input_file_path}")
        return None

    # Create a temporary directory for output if not provided
    if output_dir is None:
        temp_dir = tempfile.mkdtemp(prefix='libreoffice_')
        output_dir = temp_dir

    try:
        # Run LibreOffice headless conversion
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
            return None

        # The output file will be named <input_filename>.pdf
        base_name = os.path.splitext(os.path.basename(input_file_path))[0]
        output_pdf_path = os.path.join(output_dir, f"{base_name}.pdf")
        if not os.path.exists(output_pdf_path):
            logger.error(f"PDF output not found: {output_pdf_path}")
            return None

        return output_pdf_path

    except subprocess.TimeoutExpired:
        logger.error("LibreOffice conversion timed out (120s)")
        return None
    except Exception as e:
        logger.error(f"Unexpected conversion error: {e}")
        return None
    finally:
        # Clean up temporary directory if we created one
        if output_dir and output_dir.startswith(tempfile.gettempdir()):
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)


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

    # Convert the file
    input_path = document.file.path
    pdf_path = convert_office_to_pdf(input_path)

    if pdf_path and os.path.exists(pdf_path):
        # Save the PDF as a Django FileField
        with open(pdf_path, 'rb') as f:
            doc_file = File(f, name=f"{document.slug}_preview.pdf")
            document.preview_pdf.save(
                f"{document.slug}_preview.pdf",
                doc_file,
                save=False
            )
        document.save(update_fields=['preview_pdf'])
        # Clean up temporary PDF (if not in a temp dir, it's in the media directory already)
        # We assume convert_office_to_pdf placed it in a temp dir, so it's already cleaned up.
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