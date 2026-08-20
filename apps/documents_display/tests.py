import os
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.urls import reverse

from django.utils import timezone
from datetime import timedelta

from .models import DisplayCategory, DisplayDocument, DisplayVersion, DocumentDepartmentAccess, DocumentShare, DocumentFolder, FolderShare
from .views import get_viewable_documents
from .forms import ShareDocumentForm

User = get_user_model()


def make_pdf(name='policy.pdf'):
    return SimpleUploadedFile(name, b'%PDF-1.4 test content', content_type='application/pdf')


def dept_formset_post_data(grants=None):
    """Build a full, valid DepartmentAccessFormSet POST payload - one row
    per department in User.DEPARTMENT_CHOICES order, all unchecked except
    whatever's passed in `grants`: {department_code: {'grant': True, 'can_edit': True, ...}}."""
    grants = grants or {}
    data = {
        'form-TOTAL_FORMS': str(len(User.DEPARTMENT_CHOICES)),
        'form-INITIAL_FORMS': '0',
        'form-MIN_NUM_FORMS': '0',
        'form-MAX_NUM_FORMS': '1000',
    }
    for i, (code, _label) in enumerate(User.DEPARTMENT_CHOICES):
        data[f'form-{i}-department'] = code
        row = grants.get(code, {})
        if row.get('grant'):
            data[f'form-{i}-grant'] = 'on'
        if row.get('can_edit'):
            data[f'form-{i}-can_edit'] = 'on'
        if row.get('can_download'):
            data[f'form-{i}-can_download'] = 'on'
    return data


class DocumentShareTests(TestCase):
    """Tests for the per-user document sharing feature."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin@example.com', password='TestPass123!',
            first_name='Admin', last_name='User', department='IT', role=User.Role.ADMIN,
        )
        self.recipient = User.objects.create_user(
            email='legal@example.com', password='TestPass123!',
            first_name='Legal', last_name='Person', department='LEGAL', role=User.Role.END_USER,
        )
        self.other_user = User.objects.create_user(
            email='other@example.com', password='TestPass123!',
            first_name='Other', last_name='Person', department='LEGAL', role=User.Role.END_USER,
        )
        self.category = DisplayCategory.objects.create(name='Policies')
        # RESTRICTED with no department grants at all — recipient/other_user have zero access
        # to start with, so any access they get must come purely from the share.
        self.document = DisplayDocument.objects.create(
            title='Confidential Policy',
            category=self.category,
            file=make_pdf(),
            created_by=self.admin,
            visibility=DisplayDocument.Visibility.RESTRICTED,
        )
        self.client = Client()

    def _login_admin(self):
        self.client.login(email='admin@example.com', password='TestPass123!')

    def test_recipient_has_no_access_before_share(self):
        self.assertFalse(self.document.is_viewable_by(self.recipient))
        self.assertFalse(self.document.is_editable_by(self.recipient))
        self.assertFalse(self.document.is_downloadable_by(self.recipient))

    def test_admin_can_view_share_management_page(self):
        self._login_admin()
        response = self.client.get(reverse('documents_display:document_share', args=[self.document.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'documents_display/document_share.html')

    def test_non_admin_cannot_reach_share_management_page(self):
        self.client.login(email='legal@example.com', password='TestPass123!')
        response = self.client.get(reverse('documents_display:document_share', args=[self.document.slug]))
        self.assertNotEqual(response.status_code, 200)
        response = self.client.post(
            reverse('documents_display:document_share', args=[self.document.slug]),
            {'recipient': self.recipient.pk},
        )
        self.assertFalse(DocumentShare.objects.filter(document=self.document, recipient=self.recipient).exists())

    def test_creating_a_share_sends_email_and_grants_view_only_by_default(self):
        self._login_admin()
        with patch('apps.documents_display.views.send_email_via_brevo', return_value=(True, {})) as mock_send:
            response = self.client.post(
                reverse('documents_display:document_share', args=[self.document.slug]),
                {'recipient': self.recipient.pk},
            )
        self.assertEqual(response.status_code, 302)
        mock_send.assert_called_once()
        self.assertEqual(mock_send.call_args.kwargs['to_email'], self.recipient.email)

        share = DocumentShare.objects.get(document=self.document, recipient=self.recipient)
        self.assertTrue(share.is_active)
        self.assertFalse(share.can_edit)
        self.assertFalse(share.can_download)
        self.assertIsNotNone(share.token)

        self.assertTrue(self.document.is_viewable_by(self.recipient))
        self.assertFalse(self.document.is_editable_by(self.recipient))
        self.assertFalse(self.document.is_downloadable_by(self.recipient))
        # A third party who wasn't shared with still has nothing.
        self.assertFalse(self.document.is_viewable_by(self.other_user))

    def test_share_with_edit_and_download_grants_those_permissions(self):
        self._login_admin()
        with patch('apps.documents_display.views.send_email_via_brevo', return_value=(True, {})):
            self.client.post(
                reverse('documents_display:document_share', args=[self.document.slug]),
                {'recipient': self.recipient.pk, 'can_edit': 'on', 'can_download': 'on'},
            )
        self.assertTrue(self.document.is_viewable_by(self.recipient))
        self.assertTrue(self.document.is_editable_by(self.recipient))
        self.assertTrue(self.document.is_downloadable_by(self.recipient))

    def test_shared_document_appears_in_viewable_queryset(self):
        self._login_admin()
        with patch('apps.documents_display.views.send_email_via_brevo', return_value=(True, {})):
            self.client.post(
                reverse('documents_display:document_share', args=[self.document.slug]),
                {'recipient': self.recipient.pk},
            )
        self.assertIn(self.document, list(get_viewable_documents(self.recipient)))
        self.assertNotIn(self.document, list(get_viewable_documents(self.other_user)))

    def test_share_link_only_works_for_the_intended_recipient(self):
        self._login_admin()
        with patch('apps.documents_display.views.send_email_via_brevo', return_value=(True, {})):
            self.client.post(
                reverse('documents_display:document_share', args=[self.document.slug]),
                {'recipient': self.recipient.pk, 'can_download': 'on'},
            )
        share = DocumentShare.objects.get(document=self.document, recipient=self.recipient)
        self.client.logout()

        # Wrong user opens the link: denied, not marked accepted.
        self.client.login(email='other@example.com', password='TestPass123!')
        response = self.client.get(
            reverse('documents_display:document_share_open', args=[share.token]), follow=True
        )
        self.assertRedirects(response, reverse('documents_display:dashboard'))
        share.refresh_from_db()
        self.assertIsNone(share.accepted_at)
        self.client.logout()

        # Correct recipient opens the link: granted, marked accepted, lands on the document.
        self.client.login(email='legal@example.com', password='TestPass123!')
        response = self.client.get(
            reverse('documents_display:document_share_open', args=[share.token]), follow=True
        )
        self.assertRedirects(response, reverse('documents_display:document_detail', args=[self.document.slug]))
        share.refresh_from_db()
        self.assertIsNotNone(share.accepted_at)

    def test_revoke_removes_access(self):
        self._login_admin()
        with patch('apps.documents_display.views.send_email_via_brevo', return_value=(True, {})):
            self.client.post(
                reverse('documents_display:document_share', args=[self.document.slug]),
                {'recipient': self.recipient.pk, 'can_download': 'on'},
            )
        share = DocumentShare.objects.get(document=self.document, recipient=self.recipient)
        self.assertTrue(self.document.is_viewable_by(self.recipient))

        response = self.client.post(
            reverse('documents_display:document_share_revoke', args=[self.document.slug, share.pk])
        )
        self.assertEqual(response.status_code, 302)
        share.refresh_from_db()
        self.assertFalse(share.is_active)
        self.assertFalse(self.document.is_viewable_by(self.recipient))
        self.assertFalse(self.document.is_downloadable_by(self.recipient))

    def test_revoked_share_link_denies_access(self):
        self._login_admin()
        with patch('apps.documents_display.views.send_email_via_brevo', return_value=(True, {})):
            self.client.post(
                reverse('documents_display:document_share', args=[self.document.slug]),
                {'recipient': self.recipient.pk},
            )
        share = DocumentShare.objects.get(document=self.document, recipient=self.recipient)
        self.client.post(
            reverse('documents_display:document_share_revoke', args=[self.document.slug, share.pk])
        )
        self.client.logout()

        self.client.login(email='legal@example.com', password='TestPass123!')
        response = self.client.get(
            reverse('documents_display:document_share_open', args=[share.token]), follow=True
        )
        self.assertRedirects(response, reverse('documents_display:dashboard'))

    def test_resharing_updates_existing_share_and_can_reactivate_after_revoke(self):
        self._login_admin()
        with patch('apps.documents_display.views.send_email_via_brevo', return_value=(True, {})):
            self.client.post(
                reverse('documents_display:document_share', args=[self.document.slug]),
                {'recipient': self.recipient.pk},
            )
        share = DocumentShare.objects.get(document=self.document, recipient=self.recipient)
        old_token = share.token
        self.client.post(
            reverse('documents_display:document_share_revoke', args=[self.document.slug, share.pk])
        )
        share.refresh_from_db()
        self.assertFalse(share.is_active)

        with patch('apps.documents_display.views.send_email_via_brevo', return_value=(True, {})):
            self.client.post(
                reverse('documents_display:document_share', args=[self.document.slug]),
                {'recipient': self.recipient.pk, 'can_download': 'on'},
            )
        self.assertEqual(
            DocumentShare.objects.filter(document=self.document, recipient=self.recipient).count(), 1
        )
        share.refresh_from_db()
        self.assertTrue(share.is_active)
        self.assertTrue(share.can_download)
        self.assertNotEqual(share.token, old_token)

    def test_download_view_denied_when_share_is_view_only(self):
        self._login_admin()
        with patch('apps.documents_display.views.send_email_via_brevo', return_value=(True, {})):
            self.client.post(
                reverse('documents_display:document_share', args=[self.document.slug]),
                {'recipient': self.recipient.pk},  # view-only, no download
            )
        self.client.logout()
        self.client.login(email='legal@example.com', password='TestPass123!')

        response = self.client.get(reverse('documents_display:document_download', args=[self.document.slug]))
        self.assertEqual(response.status_code, 302)  # denied, redirected with an error message

    def test_download_view_allowed_when_share_grants_download(self):
        self._login_admin()
        with patch('apps.documents_display.views.send_email_via_brevo', return_value=(True, {})):
            self.client.post(
                reverse('documents_display:document_share', args=[self.document.slug]),
                {'recipient': self.recipient.pk, 'can_download': 'on'},
            )
        self.client.logout()
        self.client.login(email='legal@example.com', password='TestPass123!')

        response = self.client.get(reverse('documents_display:document_download', args=[self.document.slug]))
        self.assertEqual(response.status_code, 200)


class DocumentVersionDownloadTests(TestCase):
    """Tests for the permission-checked old-version download endpoint,
    replacing the raw media-URL link that used to bypass is_downloadable_by()."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin@example.com', password='TestPass123!',
            first_name='Admin', last_name='User', department='IT', role=User.Role.ADMIN,
        )
        self.viewer = User.objects.create_user(
            email='legal@example.com', password='TestPass123!',
            first_name='Legal', last_name='Person', department='LEGAL', role=User.Role.END_USER,
        )
        self.category = DisplayCategory.objects.create(name='Policies')
        self.document = DisplayDocument.objects.create(
            title='Policy', category=self.category, file=make_pdf(), created_by=self.admin,
            visibility=DisplayDocument.Visibility.RESTRICTED,
        )
        self.other_document = DisplayDocument.objects.create(
            title='Other Policy', category=self.category, file=make_pdf(name='other.pdf'),
            created_by=self.admin, visibility=DisplayDocument.Visibility.PUBLIC,
        )
        self.version = DisplayVersion.objects.create(
            document=self.document, version_number=1, file=make_pdf(name='v1.pdf'), created_by=self.admin,
        )
        self.client = Client()

    def test_denied_without_download_permission(self):
        DocumentDepartmentAccess.objects.create(document=self.document, department='LEGAL', can_download=False)
        self.client.login(email='legal@example.com', password='TestPass123!')
        response = self.client.get(
            reverse('documents_display:document_version_download', args=[self.document.slug, self.version.pk])
        )
        self.assertEqual(response.status_code, 302)

    def test_allowed_with_download_permission(self):
        DocumentDepartmentAccess.objects.create(document=self.document, department='LEGAL', can_download=True)
        self.client.login(email='legal@example.com', password='TestPass123!')
        response = self.client.get(
            reverse('documents_display:document_version_download', args=[self.document.slug, self.version.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response['Content-Disposition'])

    def test_version_scoped_to_its_own_document_404s_otherwise(self):
        """A version_id that's real but belongs to a different document than
        the slug in the URL must 404, not silently serve the wrong document's
        version (IDOR guard on the get_object_or_404 scoping)."""
        self.client.login(email='admin@example.com', password='TestPass123!')
        response = self.client.get(
            reverse('documents_display:document_version_download', args=[self.other_document.slug, self.version.pk])
        )
        self.assertEqual(response.status_code, 404)


class DocumentViewerPreviewRegenerationTests(TestCase):
    """Tests for on-demand LibreOffice preview regeneration when a document
    is viewed and its cached preview_pdf is missing."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin@example.com', password='TestPass123!',
            first_name='Admin', last_name='User', department='IT', role=User.Role.ADMIN,
        )
        self.category = DisplayCategory.objects.create(name='Policies')
        self.office_doc = DisplayDocument.objects.create(
            title='Report', category=self.category,
            file=SimpleUploadedFile('report.docx', b'fake docx content', content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
            created_by=self.admin, visibility=DisplayDocument.Visibility.PUBLIC,
        )
        self.client = Client()
        self.client.login(email='admin@example.com', password='TestPass123!')

    def test_viewer_regenerates_missing_preview(self):
        with patch('apps.documents_display.views.generate_preview_for_document', return_value=True) as mock_gen:
            response = self.client.get(reverse('documents_display:document_viewer', args=[self.office_doc.slug]))
        self.assertEqual(response.status_code, 200)
        mock_gen.assert_called_once_with(self.office_doc)

    def test_viewer_skips_regeneration_when_preview_exists(self):
        self.office_doc.preview_pdf = make_pdf(name='report_preview.pdf')
        self.office_doc.save(update_fields=['preview_pdf'])
        with patch('apps.documents_display.views.generate_preview_for_document') as mock_gen:
            response = self.client.get(reverse('documents_display:document_viewer', args=[self.office_doc.slug]))
        self.assertEqual(response.status_code, 200)
        mock_gen.assert_not_called()


class RemoteStoragePreviewGenerationTests(TestCase):
    """Regression test: generate_preview_for_document() used to call
    document.file.path unconditionally, which raises NotImplementedError on
    remote storage backends (Cloudinary in production) - meaning every
    Office-file preview silently failed to generate in production. It must
    now fall back to downloading the file when `.path` isn't available,
    mirroring apps.tickets.report_exporters._docx_image_source()."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin@example.com', password='TestPass123!',
            first_name='Admin', last_name='User', department='IT', role=User.Role.ADMIN,
        )
        self.category = DisplayCategory.objects.create(name='Policies')
        self.office_doc = DisplayDocument.objects.create(
            title='Remote Report', category=self.category,
            file=SimpleUploadedFile('remote_report.docx', b'fake docx content', content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
            created_by=self.admin, visibility=DisplayDocument.Visibility.PUBLIC,
        )

    def test_local_path_for_falls_back_to_download_when_path_unavailable(self):
        """Direct unit test of the new fallback helper, using a minimal
        duck-typed stand-in for a remote-storage FieldFile (its `.path`
        raises NotImplementedError, exactly like Cloudinary's does) - avoids
        fighting Django's real storage class resolution in a test."""
        from apps.documents_display.utils import _local_path_for

        class FakeRemoteFieldFile:
            name = 'remote_report.docx'
            url = 'https://cdn.example.com/remote_report.docx'

            @property
            def path(self):
                raise NotImplementedError('This backend does not support absolute paths.')

        fake_response = type('FakeResponse', (), {
            'content': b'downloaded office bytes',
            'raise_for_status': lambda self: None,
        })()

        with patch('apps.documents_display.utils.requests.get', return_value=fake_response) as mock_get:
            local_path, is_temp = _local_path_for(FakeRemoteFieldFile())

        mock_get.assert_called_once_with('https://cdn.example.com/remote_report.docx', timeout=30)
        self.assertTrue(is_temp)
        self.assertTrue(local_path.endswith('.docx'))
        try:
            with open(local_path, 'rb') as f:
                self.assertEqual(f.read(), b'downloaded office bytes')
        finally:
            os.remove(local_path)

    def test_generates_preview_when_storage_path_unavailable(self):
        """End-to-end: generate_preview_for_document must still succeed
        when the underlying storage's .path raises NotImplementedError -
        this is the exact scenario that silently broke every Office-file
        preview in production before this fix."""
        from apps.documents_display.utils import generate_preview_for_document

        fake_pdf_path = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False).name
        with open(fake_pdf_path, 'wb') as f:
            f.write(b'%PDF-1.4 fake')

        # input_is_temp=True with a path that doesn't really exist is fine -
        # generate_preview_for_document's os.remove() cleanup is wrapped in
        # a try/except OSError (FileNotFoundError included).
        with patch(
            'apps.documents_display.utils._local_path_for',
            return_value=('/tmp/fake_downloaded_report.docx', True),
        ) as mock_local_path, patch(
            'apps.documents_display.utils.convert_office_to_pdf', return_value=fake_pdf_path
        ) as mock_convert:
            result = generate_preview_for_document(self.office_doc)

        self.assertTrue(result)
        mock_local_path.assert_called_once()
        mock_convert.assert_called_once_with('/tmp/fake_downloaded_report.docx')
        self.office_doc.refresh_from_db()
        self.assertTrue(self.office_doc.preview_pdf)


class DocumentBulkCreateTests(TestCase):
    """Tests for the bulk-upload admin page (replaces the old standalone
    bulk-permissions screen — department grants for a batch are applied at
    upload time instead)."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin@example.com', password='TestPass123!',
            first_name='Admin', last_name='User', department='IT', role=User.Role.ADMIN,
        )
        self.non_admin = User.objects.create_user(
            email='legal@example.com', password='TestPass123!',
            first_name='Legal', last_name='Person', department='LEGAL', role=User.Role.END_USER,
        )
        self.category = DisplayCategory.objects.create(name='Policies')
        self.client = Client()

    def test_non_admin_denied(self):
        self.client.login(email='legal@example.com', password='TestPass123!')
        response = self.client.get(reverse('documents_display:document_bulk_create'))
        self.assertNotEqual(response.status_code, 200)

    def test_bulk_upload_creates_one_document_per_file_with_shared_grants(self):
        self.client.login(email='admin@example.com', password='TestPass123!')
        data = {
            'files': [make_pdf(name='a.pdf'), make_pdf(name='b.pdf')],
            'category': self.category.pk,
            'visibility': DisplayDocument.Visibility.RESTRICTED,
        }
        data.update(dept_formset_post_data({'LEGAL': {'grant': True, 'can_download': True}}))
        response = self.client.post(reverse('documents_display:document_bulk_create'), data)
        self.assertEqual(response.status_code, 302)

        docs = DisplayDocument.objects.filter(category=self.category, is_deleted=False)
        self.assertEqual(docs.count(), 2)
        self.assertEqual(set(docs.values_list('title', flat=True)), {'a', 'b'})
        for doc in docs:
            access = DocumentDepartmentAccess.objects.get(document=doc, department='LEGAL')
            self.assertTrue(access.can_download)
            self.assertFalse(access.can_edit)

    def test_permissions_url_no_longer_exists(self):
        self.client.login(email='admin@example.com', password='TestPass123!')
        with self.assertRaises(Exception):
            reverse('documents_display:document_permissions')


class ShareDocumentFormTests(TestCase):
    """Validation rules for the recipient-vs-external_email XOR and the
    external-shares-require-expiry rule."""

    def setUp(self):
        self.user = User.objects.create_user(
            email='someone@example.com', password='TestPass123!',
            first_name='Some', last_name='One', department='IT', role=User.Role.END_USER,
        )

    def test_rejects_both_recipient_and_external_email(self):
        form = ShareDocumentForm(data={'recipient': self.user.pk, 'external_email': 'a@b.com', 'expires_at': '2030-01-01'})
        self.assertFalse(form.is_valid())

    def test_rejects_neither_recipient_nor_external_email(self):
        form = ShareDocumentForm(data={})
        self.assertFalse(form.is_valid())

    def test_external_email_requires_expiry(self):
        form = ShareDocumentForm(data={'external_email': 'a@b.com'})
        self.assertFalse(form.is_valid())

    def test_external_email_with_expiry_is_valid(self):
        form = ShareDocumentForm(data={'external_email': 'a@b.com', 'expires_at': '2030-01-01'})
        self.assertTrue(form.is_valid())

    def test_internal_recipient_without_expiry_is_valid(self):
        form = ShareDocumentForm(data={'recipient': self.user.pk})
        self.assertTrue(form.is_valid())


class ExternalDocumentShareTests(TestCase):
    """Tests for no-login, token-based external document sharing."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin@example.com', password='TestPass123!',
            first_name='Admin', last_name='User', department='IT', role=User.Role.ADMIN,
        )
        self.category = DisplayCategory.objects.create(name='Policies')
        self.document = DisplayDocument.objects.create(
            title='External Policy', category=self.category, file=make_pdf(),
            created_by=self.admin, visibility=DisplayDocument.Visibility.RESTRICTED,
        )
        self.client = Client()

    def _create_share(self, **overrides):
        defaults = {
            'document': self.document,
            'external_email': 'outsider@external.com',
            'shared_by': self.admin,
            'expires_at': timezone.now() + timedelta(days=7),
        }
        defaults.update(overrides)
        return DocumentShare.objects.create(**defaults)

    def test_valid_token_shows_document_with_no_login(self):
        share = self._create_share(can_download=True)
        response = self.client.get(reverse('documents_display:document_share_external', args=[share.token]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'documents_display/document_share_external.html')
        share.refresh_from_db()
        self.assertIsNotNone(share.accepted_at)

    def test_expired_token_denies_access(self):
        share = self._create_share(expires_at=timezone.now() - timedelta(days=1))
        response = self.client.get(reverse('documents_display:document_share_external', args=[share.token]))
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(b'External Policy', response.content)

    def test_revoked_token_denies_access(self):
        share = self._create_share()
        share.revoke()
        response = self.client.get(reverse('documents_display:document_share_external', args=[share.token]))
        self.assertEqual(response.status_code, 403)

    def test_internal_share_token_not_reachable_via_external_url(self):
        """An internal (recipient-based) share's token must 404 on the
        external URL - it must not become a way to bypass document_share_open's
        'log in as the intended recipient' check."""
        internal_recipient = User.objects.create_user(
            email='internal@example.com', password='TestPass123!',
            first_name='Internal', last_name='User', department='IT', role=User.Role.END_USER,
        )
        share = DocumentShare.objects.create(document=self.document, recipient=internal_recipient, shared_by=self.admin)
        response = self.client.get(reverse('documents_display:document_share_external', args=[share.token]))
        self.assertEqual(response.status_code, 404)

    def test_download_denied_when_share_does_not_allow_it(self):
        share = self._create_share(can_download=False)
        response = self.client.get(reverse('documents_display:document_share_external_download', args=[share.token]))
        self.assertEqual(response.status_code, 403)

    def test_download_allowed_when_share_grants_it(self):
        share = self._create_share(can_download=True)
        response = self.client.get(reverse('documents_display:document_share_external_download', args=[share.token]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response['Content-Disposition'])

    def test_serve_denied_for_expired_share(self):
        share = self._create_share(expires_at=timezone.now() - timedelta(days=1))
        response = self.client.get(reverse('documents_display:document_share_external_serve', args=[share.token]))
        self.assertEqual(response.status_code, 403)

    def test_admin_creates_external_share_via_share_view(self):
        self.client.login(email='admin@example.com', password='TestPass123!')
        with patch('apps.documents_display.views.send_email_via_brevo', return_value=(True, {})) as mock_send:
            response = self.client.post(
                reverse('documents_display:document_share', args=[self.document.slug]),
                {'external_email': 'newperson@external.com', 'expires_at': '2030-01-01', 'can_download': 'on'},
            )
        self.assertEqual(response.status_code, 302)
        share = DocumentShare.objects.get(document=self.document, external_email='newperson@external.com')
        self.assertTrue(share.can_download)
        self.assertIsNotNone(share.expires_at)
        mock_send.assert_called_once()
        self.assertEqual(mock_send.call_args.kwargs['to_email'], 'newperson@external.com')
        # The emailed link must point at the no-login external URL, not the internal one.
        self.assertIn('/external/', mock_send.call_args.kwargs['html_content'])


class InternalShareExpiryTests(TestCase):
    """An internal (in-system-user) share must also respect expires_at, not
    just revoked_at."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin@example.com', password='TestPass123!',
            first_name='Admin', last_name='User', department='IT', role=User.Role.ADMIN,
        )
        self.recipient = User.objects.create_user(
            email='legal@example.com', password='TestPass123!',
            first_name='Legal', last_name='Person', department='LEGAL', role=User.Role.END_USER,
        )
        self.category = DisplayCategory.objects.create(name='Policies')
        self.document = DisplayDocument.objects.create(
            title='Expiring Policy', category=self.category, file=make_pdf(),
            created_by=self.admin, visibility=DisplayDocument.Visibility.RESTRICTED,
        )
        self.share = DocumentShare.objects.create(
            document=self.document, recipient=self.recipient, shared_by=self.admin,
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.client = Client()

    def test_expired_internal_share_denies_permission_checks(self):
        self.assertFalse(self.document.is_viewable_by(self.recipient))
        self.assertFalse(self.share.is_active)
        self.assertTrue(self.share.is_expired)

    def test_expired_internal_share_link_denies_access(self):
        self.client.login(email='legal@example.com', password='TestPass123!')
        response = self.client.get(
            reverse('documents_display:document_share_open', args=[self.share.token]), follow=True
        )
        self.assertRedirects(response, reverse('documents_display:dashboard'))


class DocumentFolderTests(TestCase):
    """Folders group several documents to be shared as one unit. Private
    to their creator (plus Superadmin) - other admins get no access."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin@example.com', password='TestPass123!',
            first_name='Admin', last_name='User', department='IT', role=User.Role.ADMIN,
        )
        self.other_admin = User.objects.create_user(
            email='otheradmin@example.com', password='TestPass123!',
            first_name='Other', last_name='Admin', department='IT', role=User.Role.ADMIN,
        )
        self.superadmin = User.objects.create_user(
            email='superadmin@example.com', password='TestPass123!',
            first_name='Super', last_name='Admin', department='IT', role=User.Role.SUPERADMIN,
        )
        self.non_admin = User.objects.create_user(
            email='enduser@example.com', password='TestPass123!',
            first_name='End', last_name='User', department='LEGAL', role=User.Role.END_USER,
        )
        self.category = DisplayCategory.objects.create(name='Policies')
        self.doc1 = DisplayDocument.objects.create(
            title='Doc One', category=self.category, file=make_pdf(name='one.pdf'),
            created_by=self.admin, visibility=DisplayDocument.Visibility.RESTRICTED,
        )
        self.doc2 = DisplayDocument.objects.create(
            title='Doc Two', category=self.category, file=make_pdf(name='two.pdf'),
            created_by=self.admin, visibility=DisplayDocument.Visibility.RESTRICTED,
        )
        self.folder = DocumentFolder.objects.create(name='Q1 Bundle', created_by=self.admin)
        self.folder.documents.add(self.doc1, self.doc2)
        self.client = Client()

    def _login_admin(self):
        self.client.login(email='admin@example.com', password='TestPass123!')

    def test_non_admin_denied_folder_list(self):
        self.client.login(email='enduser@example.com', password='TestPass123!')
        response = self.client.get(reverse('documents_display:folder_list'))
        self.assertNotEqual(response.status_code, 200)

    def test_creating_a_folder(self):
        self._login_admin()
        response = self.client.post(reverse('documents_display:folder_list'), {'name': 'New Folder', 'description': 'x'})
        self.assertEqual(response.status_code, 302)
        folder = DocumentFolder.objects.get(name='New Folder')
        self.assertEqual(folder.created_by, self.admin)

    def test_folder_is_private_to_creator(self):
        """Another Admin (not the creator) gets denied on every management
        view for this folder - creator + Superadmin only."""
        self.client.login(email='otheradmin@example.com', password='TestPass123!')
        response = self.client.get(reverse('documents_display:folder_detail', args=[self.folder.slug]))
        self.assertEqual(response.status_code, 302)  # redirected with an error, not shown the folder
        response = self.client.post(
            reverse('documents_display:folder_add_documents', args=[self.folder.slug]), {'document_ids': [self.doc1.pk]}
        )
        self.assertEqual(response.status_code, 403)
        response = self.client.post(reverse('documents_display:folder_delete', args=[self.folder.slug]))
        self.assertEqual(response.status_code, 403)
        # Folder must still exist - the delete attempt was denied, not silently applied.
        self.assertTrue(DocumentFolder.objects.filter(pk=self.folder.pk).exists())

    def test_superadmin_can_manage_any_folder(self):
        self.client.login(email='superadmin@example.com', password='TestPass123!')
        response = self.client.get(reverse('documents_display:folder_detail', args=[self.folder.slug]))
        self.assertEqual(response.status_code, 200)

    def test_folder_list_only_shows_own_folders_for_non_superadmin(self):
        DocumentFolder.objects.create(name='Someone Elses', created_by=self.other_admin)
        self._login_admin()
        response = self.client.get(reverse('documents_display:folder_list'))
        self.assertContains(response, 'Q1 Bundle')
        self.assertNotContains(response, 'Someone Elses')

    def test_add_and_remove_documents(self):
        self._login_admin()
        doc3 = DisplayDocument.objects.create(
            title='Doc Three', category=self.category, file=make_pdf(name='three.pdf'),
            created_by=self.admin, visibility=DisplayDocument.Visibility.RESTRICTED,
        )
        self.client.post(
            reverse('documents_display:folder_add_documents', args=[self.folder.slug]), {'document_ids': [doc3.pk]}
        )
        self.assertIn(doc3, self.folder.documents.all())

        self.client.post(reverse('documents_display:folder_remove_document', args=[self.folder.slug, doc3.pk]))
        self.assertNotIn(doc3, self.folder.documents.all())

    def test_delete_folder_cascades_shares(self):
        share = FolderShare.objects.create(folder=self.folder, recipient=self.non_admin, shared_by=self.admin)
        self._login_admin()
        self.client.post(reverse('documents_display:folder_delete', args=[self.folder.slug]))
        self.assertFalse(DocumentFolder.objects.filter(pk=self.folder.pk).exists())
        self.assertFalse(FolderShare.objects.filter(pk=share.pk).exists())


class InternalFolderShareTests(TestCase):
    """Sharing a folder with an in-system user grants view/download access
    to every document inside it, without touching each document's own
    permission grants."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin@example.com', password='TestPass123!',
            first_name='Admin', last_name='User', department='IT', role=User.Role.ADMIN,
        )
        self.recipient = User.objects.create_user(
            email='legal@example.com', password='TestPass123!',
            first_name='Legal', last_name='Person', department='LEGAL', role=User.Role.END_USER,
        )
        self.other_user = User.objects.create_user(
            email='other@example.com', password='TestPass123!',
            first_name='Other', last_name='Person', department='LEGAL', role=User.Role.END_USER,
        )
        self.category = DisplayCategory.objects.create(name='Policies')
        self.doc1 = DisplayDocument.objects.create(
            title='Folder Doc One', category=self.category, file=make_pdf(name='fone.pdf'),
            created_by=self.admin, visibility=DisplayDocument.Visibility.RESTRICTED,
        )
        self.doc2 = DisplayDocument.objects.create(
            title='Folder Doc Two', category=self.category, file=make_pdf(name='ftwo.pdf'),
            created_by=self.admin, visibility=DisplayDocument.Visibility.RESTRICTED,
        )
        self.folder = DocumentFolder.objects.create(name='Shared Bundle', created_by=self.admin)
        self.folder.documents.add(self.doc1, self.doc2)
        self.client = Client()

    def test_no_access_before_share(self):
        self.assertFalse(self.doc1.is_viewable_by(self.recipient))
        self.assertFalse(self.doc2.is_viewable_by(self.recipient))

    def test_sharing_grants_view_access_to_every_document_in_folder(self):
        self.client.login(email='admin@example.com', password='TestPass123!')
        with patch('apps.documents_display.views.send_email_via_brevo', return_value=(True, {})) as mock_send:
            response = self.client.post(
                reverse('documents_display:folder_share', args=[self.folder.slug]),
                {'recipient': self.recipient.pk, 'can_download': 'on'},
            )
        self.assertEqual(response.status_code, 302)
        mock_send.assert_called_once()

        self.assertTrue(self.doc1.is_viewable_by(self.recipient))
        self.assertTrue(self.doc2.is_viewable_by(self.recipient))
        self.assertTrue(self.doc1.is_downloadable_by(self.recipient))
        self.assertIn(self.doc1, list(get_viewable_documents(self.recipient)))
        # A third party who wasn't shared with still has nothing.
        self.assertFalse(self.doc1.is_viewable_by(self.other_user))

    def test_share_link_only_works_for_the_intended_recipient(self):
        share = FolderShare.objects.create(folder=self.folder, recipient=self.recipient, shared_by=self.admin)

        self.client.login(email='other@example.com', password='TestPass123!')
        response = self.client.get(
            reverse('documents_display:folder_share_open', args=[share.token]), follow=True
        )
        self.assertRedirects(response, reverse('documents_display:dashboard'))
        self.client.logout()

        self.client.login(email='legal@example.com', password='TestPass123!')
        response = self.client.get(
            reverse('documents_display:folder_share_open', args=[share.token]), follow=True
        )
        self.assertRedirects(response, reverse('documents_display:folder_shared_view', args=[share.token]))
        share.refresh_from_db()
        self.assertIsNotNone(share.accepted_at)

    def test_revoke_removes_access_to_every_document(self):
        share = FolderShare.objects.create(folder=self.folder, recipient=self.recipient, shared_by=self.admin, can_download=True)
        self.assertTrue(self.doc1.is_viewable_by(self.recipient))
        share.revoke()
        self.assertFalse(self.doc1.is_viewable_by(self.recipient))
        self.assertFalse(self.doc2.is_viewable_by(self.recipient))

    def test_expired_folder_share_denies_access(self):
        share = FolderShare.objects.create(
            folder=self.folder, recipient=self.recipient, shared_by=self.admin,
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.assertFalse(self.doc1.is_viewable_by(self.recipient))
        self.assertFalse(share.is_active)


class ExternalFolderShareTests(TestCase):
    """No-login, token-based external folder sharing."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin@example.com', password='TestPass123!',
            first_name='Admin', last_name='User', department='IT', role=User.Role.ADMIN,
        )
        self.category = DisplayCategory.objects.create(name='Policies')
        self.doc1 = DisplayDocument.objects.create(
            title='External Folder Doc', category=self.category, file=make_pdf(name='efone.pdf'),
            created_by=self.admin, visibility=DisplayDocument.Visibility.RESTRICTED,
        )
        self.folder = DocumentFolder.objects.create(name='External Bundle', created_by=self.admin)
        self.folder.documents.add(self.doc1)
        self.client = Client()

    def _create_share(self, **overrides):
        defaults = {
            'folder': self.folder,
            'external_email': 'outsider@external.com',
            'shared_by': self.admin,
            'expires_at': timezone.now() + timedelta(days=7),
        }
        defaults.update(overrides)
        return FolderShare.objects.create(**defaults)

    def test_valid_token_shows_folder_with_no_login(self):
        share = self._create_share(can_download=True)
        response = self.client.get(reverse('documents_display:folder_share_external', args=[share.token]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'documents_display/folder_share_external.html')
        self.assertContains(response, 'External Folder Doc')
        share.refresh_from_db()
        self.assertIsNotNone(share.accepted_at)

    def test_expired_token_denies_access(self):
        share = self._create_share(expires_at=timezone.now() - timedelta(days=1))
        response = self.client.get(reverse('documents_display:folder_share_external', args=[share.token]))
        self.assertEqual(response.status_code, 403)

    def test_revoked_token_denies_access(self):
        share = self._create_share()
        share.revoke()
        response = self.client.get(reverse('documents_display:folder_share_external', args=[share.token]))
        self.assertEqual(response.status_code, 403)

    def test_internal_share_token_not_reachable_via_external_url(self):
        internal_recipient = User.objects.create_user(
            email='internal@example.com', password='TestPass123!',
            first_name='Internal', last_name='User', department='IT', role=User.Role.END_USER,
        )
        share = FolderShare.objects.create(folder=self.folder, recipient=internal_recipient, shared_by=self.admin)
        response = self.client.get(reverse('documents_display:folder_share_external', args=[share.token]))
        self.assertEqual(response.status_code, 404)

    def test_serve_and_download_scoped_to_documents_actually_in_the_folder(self):
        """A document that isn't in the shared folder must not be servable
        via that folder's token, even if the document exists."""
        other_doc = DisplayDocument.objects.create(
            title='Not In Folder', category=self.category, file=make_pdf(name='notin.pdf'),
            created_by=self.admin, visibility=DisplayDocument.Visibility.RESTRICTED,
        )
        share = self._create_share(can_download=True)

        response = self.client.get(
            reverse('documents_display:folder_share_external_serve', args=[share.token, self.doc1.pk])
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.get(
            reverse('documents_display:folder_share_external_serve', args=[share.token, other_doc.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_download_denied_when_share_does_not_allow_it(self):
        share = self._create_share(can_download=False)
        response = self.client.get(
            reverse('documents_display:folder_share_external_download', args=[share.token, self.doc1.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_download_allowed_when_share_grants_it(self):
        share = self._create_share(can_download=True)
        response = self.client.get(
            reverse('documents_display:folder_share_external_download', args=[share.token, self.doc1.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response['Content-Disposition'])
