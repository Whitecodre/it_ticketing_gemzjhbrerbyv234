from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.urls import reverse

from django.utils import timezone
from datetime import timedelta

from .models import DisplayCategory, DisplayDocument, DisplayVersion, DocumentDepartmentAccess, DocumentShare
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


class DocumentBulkPermissionsTests(TestCase):
    """Tests for the bulk permissions admin page."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin@example.com', password='TestPass123!',
            first_name='Admin', last_name='User', department='IT', role=User.Role.ADMIN,
        )
        self.non_admin = User.objects.create_user(
            email='legal@example.com', password='TestPass123!',
            first_name='Legal', last_name='Person', department='LEGAL', role=User.Role.END_USER,
        )
        self.recipient = User.objects.create_user(
            email='newhire@example.com', password='TestPass123!',
            first_name='New', last_name='Hire', department='HR', role=User.Role.END_USER,
        )
        self.category = DisplayCategory.objects.create(name='Policies')
        self.doc_a = DisplayDocument.objects.create(
            title='Doc A', category=self.category, file=make_pdf(name='a.pdf'),
            created_by=self.admin, visibility=DisplayDocument.Visibility.RESTRICTED,
        )
        self.doc_b = DisplayDocument.objects.create(
            title='Doc B', category=self.category, file=make_pdf(name='b.pdf'),
            created_by=self.admin, visibility=DisplayDocument.Visibility.RESTRICTED,
        )
        self.doc_untouched = DisplayDocument.objects.create(
            title='Doc Untouched', category=self.category, file=make_pdf(name='c.pdf'),
            created_by=self.admin, visibility=DisplayDocument.Visibility.RESTRICTED,
        )
        # Pre-existing grant on an unrelated department, to prove the bulk
        # action doesn't touch grants it wasn't told about.
        DocumentDepartmentAccess.objects.create(document=self.doc_a, department='IT', can_download=True)
        self.client = Client()

    def test_non_admin_denied(self):
        self.client.login(email='legal@example.com', password='TestPass123!')
        response = self.client.get(reverse('documents_display:document_permissions'))
        self.assertNotEqual(response.status_code, 200)

    def test_bulk_department_grant_applies_to_selected_documents_only(self):
        self.client.login(email='admin@example.com', password='TestPass123!')
        data = {
            'document_ids': [self.doc_a.pk, self.doc_b.pk],
        }
        data.update(dept_formset_post_data({'LEGAL': {'grant': True, 'can_download': True}}))
        response = self.client.post(reverse('documents_display:document_permissions'), data)
        self.assertEqual(response.status_code, 302)

        for doc in (self.doc_a, self.doc_b):
            access = DocumentDepartmentAccess.objects.get(document=doc, department='LEGAL')
            self.assertTrue(access.can_download)
            self.assertFalse(access.can_edit)

        # Untouched document got nothing.
        self.assertFalse(DocumentDepartmentAccess.objects.filter(document=self.doc_untouched, department='LEGAL').exists())
        # Pre-existing IT grant on doc_a survives unchanged.
        it_access = DocumentDepartmentAccess.objects.get(document=self.doc_a, department='IT')
        self.assertTrue(it_access.can_download)


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
