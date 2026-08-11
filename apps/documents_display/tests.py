from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.urls import reverse

from .models import DisplayCategory, DisplayDocument, DocumentShare
from .views import get_viewable_documents

User = get_user_model()


def make_pdf(name='policy.pdf'):
    return SimpleUploadedFile(name, b'%PDF-1.4 test content', content_type='application/pdf')


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
