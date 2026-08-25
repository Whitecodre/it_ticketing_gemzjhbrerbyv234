import io
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from apps.knowledge_base.models import Article, ArticleVersion, ArticleFeedback
from apps.common.models import Category, Tag
from apps.tickets.models import Ticket, TicketComment

User = get_user_model()

# 1x1 transparent PNG, used to test the KB image upload endpoint.
TINY_PNG_BYTES = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00'
    b'\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\x18\xdd\x8d'
    b'\xb0\x00\x00\x00\x00IEND\xaeB`\x82'
)


class ArticleModelTests(TestCase):
    """Test Article model."""

    def setUp(self):
        self.author = User.objects.create_user(
            email='author@example.com',
            password='TestPass123!',
            first_name='Author',
            last_name='User',
            department='IT',
            role=User.Role.AGENT,
            is_active=True,
            email_verified=True
        )
        self.category = Category.objects.create(name='IT', slug='it')

    def test_article_creation(self):
        article = Article.objects.create(
            title='Test Article',
            slug='test-article',
            content='Test content',
            author=self.author,
            category=self.category,
            status=Article.Status.DRAFT
        )
        self.assertEqual(article.title, 'Test Article')
        self.assertEqual(article.author, self.author)
        self.assertEqual(article.status, Article.Status.DRAFT)
        self.assertEqual(str(article), 'Test Article')

    def test_article_slug_auto_generation(self):
        article = Article.objects.create(
            title='Test Article With Spaces',
            content='Test content',
            author=self.author,
            category=self.category
        )
        self.assertTrue(article.slug.startswith('test-article-with-spaces'))

    def test_article_version_creation(self):
        article = Article.objects.create(
            title='Test Article',
            slug='test-article',
            content='Original content',
            author=self.author,
            category=self.category
        )
        version = ArticleVersion.objects.create(
            article=article,
            content='Updated content',
            edited_by=self.author
        )
        self.assertEqual(version.article, article)
        self.assertEqual(version.content, 'Updated content')
        self.assertEqual(version.edited_by, self.author)


class KnowledgeBaseViewTests(TestCase):
    """Test knowledge base views."""

    def setUp(self):
        self.client = Client()
        self.author = User.objects.create_user(
            email='author@example.com',
            password='TestPass123!',
            first_name='Author',
            last_name='User',
            department='IT',
            role=User.Role.AGENT,
            is_active=True,
            email_verified=True
        )
        self.category = Category.objects.create(name='IT', slug='it')
        self.client.login(email='author@example.com', password='TestPass123!')

    def test_kb_management_page_loads(self):
        """Test KB management page loads for authenticated agent."""
        response = self.client.get(reverse('kb:management'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'knowledge_base/management.html')

    def test_kb_management_denied_for_non_it_team_lead(self):
        """A Team Lead outside IT is scoped to the approval flow only."""
        non_it_lead = User.objects.create_user(
            email='marineleadkb@example.com', password='TestPass123!',
            first_name='Marine', last_name='Lead', department='MARINE',
            role=User.Role.TEAM_LEAD, is_active=True, email_verified=True,
        )
        self.client.logout()
        self.client.login(email='marineleadkb@example.com', password='TestPass123!')
        response = self.client.get(reverse('kb:management'))
        self.assertEqual(response.status_code, 403)

    def test_article_create(self):
        """Test creating a new article draft (wizard step 1 — metadata only, AJAX)."""
        response = self.client.post(reverse('kb:create'), {
            'title': 'New Article',
            'category': self.category.id,
            'visibility': 'PUBLIC'
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'ok')
        article = Article.objects.get(title='New Article')
        self.assertEqual(article.status, Article.Status.DRAFT)
        self.assertIn(str(article.pk), data['redirect'])

    def test_article_edit(self):
        """Test editing an article's content (wizard step 2)."""
        article = Article.objects.create(
            title='Test Article',
            slug='test-article',
            content='Original content',
            author=self.author,
            category=self.category,
            status=Article.Status.DRAFT
        )
        response = self.client.post(reverse('kb:edit_content', args=[article.pk]), {
            'content': 'Updated content',
        })
        self.assertEqual(response.status_code, 302)
        article.refresh_from_db()
        self.assertEqual(article.content, 'Updated content')

    def test_article_metadata_update(self):
        """Test editing an article's title/category/visibility/tags separately from content."""
        article = Article.objects.create(
            title='Test Article',
            slug='test-article',
            content='Original content',
            author=self.author,
            category=self.category,
            status=Article.Status.DRAFT
        )
        response = self.client.post(reverse('kb:metadata_update', args=[article.pk]), {
            'title': 'Updated Article',
            'category': self.category.id,
            'visibility': 'PUBLIC'
        })
        self.assertEqual(response.status_code, 200)
        article.refresh_from_db()
        self.assertEqual(article.title, 'Updated Article')
        self.assertEqual(article.visibility, 'PUBLIC')

    def test_kb_portal_loads(self):
        """Bare portal load (no search/category/tag) shows category cards,
        not individual articles — the article grid is filter results, not
        a default listing of everything published."""
        Article.objects.create(
            title='Published Article',
            slug='published-article',
            content='Published content',
            author=self.author,
            category=self.category,
            status=Article.Status.PUBLISHED,
            visibility='PUBLIC'
        )
        response = self.client.get(reverse('kb:portal'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Published Article')
        self.assertContains(response, self.category.name)

    def test_kb_portal_shows_articles_for_selected_category(self):
        """Selecting a category surfaces its articles in the grid."""
        Article.objects.create(
            title='Published Article',
            slug='published-article',
            content='Published content',
            author=self.author,
            category=self.category,
            status=Article.Status.PUBLISHED,
            visibility='PUBLIC'
        )
        response = self.client.get(reverse('kb:portal'), {'category': self.category.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Published Article')


class KnowledgeBaseProductionReadinessTests(TestCase):
    """Correctness/security fixes: broken reject-review URL, CSRF-unsafe
    GET-based state changes, publish bypassing review, unreachable internal
    articles, missing auth on tag autocomplete, and content sanitization."""

    def setUp(self):
        self.client = Client()
        self.author = User.objects.create_user(
            email='kbauthor@example.com', password='TestPass123!',
            first_name='KB', last_name='Author', department='IT',
            role=User.Role.AGENT, is_active=True, email_verified=True,
        )
        self.lead = User.objects.create_user(
            email='kblead@example.com', password='TestPass123!',
            first_name='KB', last_name='Lead', department='IT',
            role=User.Role.TEAM_LEAD, is_active=True, email_verified=True,
        )
        self.end_user = User.objects.create_user(
            email='kbenduser@example.com', password='TestPass123!',
            first_name='KB', last_name='User', department='IT',
            role=User.Role.END_USER, is_active=True, email_verified=True,
        )
        self.category = Category.objects.create(name='IT', slug='it-prod')

    def _make_article(self, status=Article.Status.PENDING_REVIEW, visibility='PUBLIC'):
        return Article.objects.create(
            title='Prod Readiness Article', slug=f'prod-readiness-{Article.objects.count()}',
            content='<p>Body</p>', author=self.author, category=self.category,
            status=status, visibility=visibility,
        )

    def test_reject_review_does_not_crash(self):
        """Previously reverse('kb:edit', ...) raised NoReverseMatch here."""
        article = self._make_article(status=Article.Status.PENDING_REVIEW)
        self.client.login(email='kblead@example.com', password='TestPass123!')
        response = self.client.post(reverse('kb:reject_review', args=[article.pk]), {'reason': 'Needs work'})
        self.assertEqual(response.status_code, 302)
        article.refresh_from_db()
        self.assertEqual(article.status, Article.Status.DRAFT)

    def test_submit_review_publish_archive_reject_get(self):
        """These three state-changing views must no longer accept GET."""
        article = self._make_article(status=Article.Status.DRAFT)
        self.client.login(email='kbauthor@example.com', password='TestPass123!')
        response = self.client.get(reverse('kb:submit_review', args=[article.pk]))
        self.assertEqual(response.status_code, 405)

        self.client.logout()
        self.client.login(email='kblead@example.com', password='TestPass123!')
        response = self.client.get(reverse('kb:publish', args=[article.pk]))
        self.assertEqual(response.status_code, 405)
        response = self.client.get(reverse('kb:archive', args=[article.pk]))
        self.assertEqual(response.status_code, 405)

    def test_publish_requires_pending_review(self):
        article = self._make_article(status=Article.Status.DRAFT)
        self.client.login(email='kblead@example.com', password='TestPass123!')
        response = self.client.post(reverse('kb:publish', args=[article.pk]))
        self.assertEqual(response.status_code, 302)
        article.refresh_from_db()
        self.assertEqual(article.status, Article.Status.DRAFT)

    def test_publish_succeeds_from_pending_review(self):
        article = self._make_article(status=Article.Status.PENDING_REVIEW)
        self.client.login(email='kblead@example.com', password='TestPass123!')
        response = self.client.post(reverse('kb:publish', args=[article.pk]))
        self.assertEqual(response.status_code, 302)
        article.refresh_from_db()
        self.assertEqual(article.status, Article.Status.PUBLISHED)

    def test_internal_article_reachable_by_staff_not_by_others(self):
        article = self._make_article(status=Article.Status.PUBLISHED, visibility='INTERNAL')
        self.client.login(email='kblead@example.com', password='TestPass123!')
        response = self.client.get(reverse('kb:article_detail', args=[article.slug]))
        self.assertEqual(response.status_code, 200)

        self.client.logout()
        self.client.login(email='kbenduser@example.com', password='TestPass123!')
        response = self.client.get(reverse('kb:article_detail', args=[article.slug]))
        self.assertEqual(response.status_code, 404)

    def test_tag_autocomplete_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse('kb:tag_autocomplete'), {'q': 'a'})
        self.assertIn(response.status_code, (302, 401, 403))

    def test_article_content_is_sanitized_on_save(self):
        article = Article.objects.create(
            title='Sanitize Me', slug='sanitize-me', content='', author=self.author,
            category=self.category, status=Article.Status.DRAFT,
        )
        self.client.login(email='kbauthor@example.com', password='TestPass123!')
        self.client.post(reverse('kb:edit_content', args=[article.pk]), {
            'content': '<p>Hello</p><script>alert(1)</script><img src=x onerror=alert(2)>',
        })
        article.refresh_from_db()
        self.assertNotIn('<script', article.content)
        self.assertNotIn('onerror', article.content)
        self.assertIn('Hello', article.content)

    def test_article_content_sanitization_preserves_allowed_formatting(self):
        article = Article.objects.create(
            title='Format Me', slug='format-me', content='', author=self.author,
            category=self.category, status=Article.Status.DRAFT,
        )
        self.client.login(email='kbauthor@example.com', password='TestPass123!')
        rich_content = '<p><strong>Bold</strong> <em>italic</em></p><ul><li>Item</li></ul><a href="https://example.com">link</a>'
        self.client.post(reverse('kb:edit_content', args=[article.pk]), {'content': rich_content})
        article.refresh_from_db()
        self.assertIn('<strong>Bold</strong>', article.content)
        self.assertIn('<li>Item</li>', article.content)
        self.assertIn('href="https://example.com"', article.content)

    def test_publish_sets_published_at_and_by_once(self):
        article = self._make_article(status=Article.Status.PENDING_REVIEW)
        self.client.login(email='kblead@example.com', password='TestPass123!')
        self.client.post(reverse('kb:publish', args=[article.pk]))
        article.refresh_from_db()
        self.assertIsNotNone(article.published_at)
        self.assertEqual(article.published_by, self.lead)

        first_published_at = article.published_at
        # Simulate a later re-publish cycle (edit -> submit -> publish again)
        # and confirm published_at/published_by aren't clobbered.
        article.status = Article.Status.PENDING_REVIEW
        article.save()
        self.client.post(reverse('kb:publish', args=[article.pk]))
        article.refresh_from_db()
        self.assertEqual(article.published_at, first_published_at)
        self.assertEqual(article.published_by, self.lead)


class EditAfterPublishTests(TestCase):
    """A published article can be edited in place by its author or an
    elevated role, without losing PUBLISHED status or forcing re-review."""

    def setUp(self):
        self.client = Client()
        self.author = User.objects.create_user(
            email='pubauthor@example.com', password='TestPass123!',
            first_name='Pub', last_name='Author', department='IT',
            role=User.Role.AGENT, is_active=True, email_verified=True,
        )
        self.other_agent = User.objects.create_user(
            email='pubother@example.com', password='TestPass123!',
            first_name='Pub', last_name='Other', department='IT',
            role=User.Role.AGENT, is_active=True, email_verified=True,
        )
        self.lead = User.objects.create_user(
            email='publead@example.com', password='TestPass123!',
            first_name='Pub', last_name='Lead', department='IT',
            role=User.Role.TEAM_LEAD, is_active=True, email_verified=True,
        )
        self.category = Category.objects.create(name='IT', slug='it-pub')
        self.article = Article.objects.create(
            title='Published Article', slug='published-edit-test',
            content='Original content', author=self.author, category=self.category,
            status=Article.Status.PUBLISHED, visibility='PUBLIC',
        )

    def test_author_can_edit_published_article_in_place(self):
        self.client.login(email='pubauthor@example.com', password='TestPass123!')
        response = self.client.post(reverse('kb:edit_content', args=[self.article.pk]), {
            'content': 'Updated published content',
        })
        self.assertEqual(response.status_code, 302)
        self.article.refresh_from_db()
        self.assertEqual(self.article.content, 'Updated published content')
        self.assertEqual(self.article.status, Article.Status.PUBLISHED)
        self.assertEqual(ArticleVersion.objects.filter(article=self.article).count(), 1)

    def test_team_lead_can_edit_published_article(self):
        self.client.login(email='publead@example.com', password='TestPass123!')
        response = self.client.post(reverse('kb:edit_content', args=[self.article.pk]), {
            'content': 'Lead-edited content',
        })
        self.assertEqual(response.status_code, 302)
        self.article.refresh_from_db()
        self.assertEqual(self.article.content, 'Lead-edited content')
        self.assertEqual(self.article.status, Article.Status.PUBLISHED)

    def test_other_agent_cannot_edit_published_article(self):
        self.client.login(email='pubother@example.com', password='TestPass123!')
        response = self.client.post(reverse('kb:edit_content', args=[self.article.pk]), {
            'content': 'Should not save',
        })
        self.assertEqual(response.status_code, 403)
        self.article.refresh_from_db()
        self.assertEqual(self.article.content, 'Original content')

    def test_management_published_tab_shows_edit_link_for_author(self):
        self.client.login(email='pubauthor@example.com', password='TestPass123!')
        response = self.client.get(reverse('kb:management'))
        self.assertContains(response, reverse('kb:edit_content', args=[self.article.pk]))

    def test_article_detail_shows_edit_link_for_author(self):
        self.client.login(email='pubauthor@example.com', password='TestPass123!')
        response = self.client.get(reverse('kb:article_detail', args=[self.article.slug]))
        self.assertContains(response, reverse('kb:edit_content', args=[self.article.pk]))


class ArchiveRestoreTests(TestCase):
    """Archiving remembers the prior status so Restore puts an article back
    where it came from, and both actions stay TEAM_LEAD/ADMIN/SUPERADMIN-only."""

    def setUp(self):
        self.client = Client()
        self.author = User.objects.create_user(
            email='archauthor@example.com', password='TestPass123!',
            first_name='Arch', last_name='Author', department='IT',
            role=User.Role.AGENT, is_active=True, email_verified=True,
        )
        self.lead = User.objects.create_user(
            email='archlead@example.com', password='TestPass123!',
            first_name='Arch', last_name='Lead', department='IT',
            role=User.Role.TEAM_LEAD, is_active=True, email_verified=True,
        )
        self.category = Category.objects.create(name='IT', slug='it-arch')
        self.client.login(email='archlead@example.com', password='TestPass123!')

    def _make_article(self, status):
        return Article.objects.create(
            title='Archive Test Article', slug=f'archive-test-{Article.objects.count()}',
            content='Body', author=self.author, category=self.category, status=status,
        )

    def test_archive_records_prior_status(self):
        article = self._make_article(Article.Status.PUBLISHED)
        self.client.post(reverse('kb:archive', args=[article.pk]))
        article.refresh_from_db()
        self.assertEqual(article.status, Article.Status.ARCHIVED)
        self.assertEqual(article.archived_from_status, Article.Status.PUBLISHED)

    def test_restore_returns_to_prior_status(self):
        article = self._make_article(Article.Status.PUBLISHED)
        self.client.post(reverse('kb:archive', args=[article.pk]))
        self.client.post(reverse('kb:restore', args=[article.pk]))
        article.refresh_from_db()
        self.assertEqual(article.status, Article.Status.PUBLISHED)
        self.assertIsNone(article.archived_from_status)

    def test_restore_from_draft_returns_to_draft(self):
        article = self._make_article(Article.Status.DRAFT)
        self.client.post(reverse('kb:archive', args=[article.pk]))
        self.client.post(reverse('kb:restore', args=[article.pk]))
        article.refresh_from_db()
        self.assertEqual(article.status, Article.Status.DRAFT)

    def test_restore_rejects_non_archived_article(self):
        article = self._make_article(Article.Status.DRAFT)
        response = self.client.post(reverse('kb:restore', args=[article.pk]))
        self.assertEqual(response.status_code, 302)
        article.refresh_from_db()
        self.assertEqual(article.status, Article.Status.DRAFT)

    def test_author_cannot_archive(self):
        article = self._make_article(Article.Status.PUBLISHED)
        self.client.logout()
        self.client.login(email='archauthor@example.com', password='TestPass123!')
        response = self.client.post(reverse('kb:archive', args=[article.pk]))
        self.assertEqual(response.status_code, 403)

    def test_author_cannot_restore(self):
        article = self._make_article(Article.Status.ARCHIVED)
        article.archived_from_status = Article.Status.PUBLISHED
        article.save()
        self.client.logout()
        self.client.login(email='archauthor@example.com', password='TestPass123!')
        response = self.client.post(reverse('kb:restore', args=[article.pk]))
        self.assertEqual(response.status_code, 403)

    def test_management_page_shows_archived_tab_and_article(self):
        article = self._make_article(Article.Status.PUBLISHED)
        self.client.post(reverse('kb:archive', args=[article.pk]))
        response = self.client.get(reverse('kb:management'))
        self.assertContains(response, 'Archived')
        self.assertContains(response, 'Archive Test Article')
        self.assertContains(response, reverse('kb:restore', args=[article.pk]))


class KBImageUploadTests(TestCase):
    """Real image upload for the editor — replaces the old URL-only /
    paste-as-base64 flow."""

    def setUp(self):
        self.client = Client()
        self.agent = User.objects.create_user(
            email='imgagent@example.com', password='TestPass123!',
            first_name='Img', last_name='Agent', department='IT',
            role=User.Role.AGENT, is_active=True, email_verified=True,
        )
        self.client.login(email='imgagent@example.com', password='TestPass123!')

    def test_upload_success_returns_url(self):
        image = SimpleUploadedFile('test.png', TINY_PNG_BYTES, content_type='image/png')
        response = self.client.post(reverse('kb:image_upload'), {'image': image})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('url', data)
        self.assertTrue(data['url'])

    def test_upload_rejects_disallowed_mime(self):
        bad_file = SimpleUploadedFile('test.txt', b'not an image', content_type='text/plain')
        response = self.client.post(reverse('kb:image_upload'), {'image': bad_file})
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())

    def test_upload_requires_kb_role(self):
        end_user = User.objects.create_user(
            email='imguser@example.com', password='TestPass123!',
            first_name='Img', last_name='User', department='IT',
            role=User.Role.END_USER, is_active=True, email_verified=True,
        )
        self.client.logout()
        self.client.login(email='imguser@example.com', password='TestPass123!')
        image = SimpleUploadedFile('test.png', TINY_PNG_BYTES, content_type='image/png')
        response = self.client.post(reverse('kb:image_upload'), {'image': image})
        self.assertEqual(response.status_code, 403)

    def test_upload_requires_a_file(self):
        response = self.client.post(reverse('kb:image_upload'), {})
        self.assertEqual(response.status_code, 400)


class TicketConversionTests(TestCase):
    """Ticket → KB conversion: metadata-only step, real-HTML scaffold (not
    the old literal **bold** Markdown mixed into HTML), category override,
    and hand-off into the same editor every other article uses."""

    def setUp(self):
        self.client = Client()
        self.agent = User.objects.create_user(
            email='convagent@example.com', password='TestPass123!',
            first_name='Conv', last_name='Agent', department='IT',
            role=User.Role.AGENT, is_active=True, email_verified=True,
        )
        self.requester = User.objects.create_user(
            email='convrequester@example.com', password='TestPass123!',
            first_name='Conv', last_name='Requester', department='IT',
            role=User.Role.END_USER, is_active=True, email_verified=True,
        )
        self.ticket_category = Category.objects.create(name='Networking', slug='networking')
        self.kb_category = Category.objects.create(name='How-Tos', slug='how-tos')
        self.client.login(email='convagent@example.com', password='TestPass123!')
        self.ticket = Ticket.objects.create(
            type=Ticket.Type.INCIDENT,
            title='VPN keeps disconnecting',
            description='VPN drops every 10 minutes.',
            requester=self.requester,
            category=self.ticket_category,
            resolution_root_cause='Stale DNS cache.',
            resolution_steps='Flushed DNS and restarted the VPN client.',
        )

    def test_get_shows_metadata_form_only(self):
        response = self.client.get(reverse('kb:convert_ticket', args=[self.ticket.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="title"')
        self.assertContains(response, 'name="category"')
        self.assertNotContains(response, 'tinymce')

    def test_post_creates_draft_with_real_html_and_redirects_to_editor(self):
        response = self.client.post(reverse('kb:convert_ticket', args=[self.ticket.pk]), {
            'title': 'How to fix VPN drops',
            'category': self.kb_category.pk,
            'visibility': 'INTERNAL',
            'include_comment': [],
        })
        article = Article.objects.get(title='How to fix VPN drops')
        self.assertRedirects(response, reverse('kb:edit_content', args=[article.pk]))
        self.assertEqual(article.status, Article.Status.DRAFT)
        self.assertEqual(article.category, self.kb_category)  # override, not silently inherited
        self.assertIn('Stale DNS cache.', article.content)
        self.assertIn('<h3>Root Cause</h3>', article.content)
        self.assertNotIn('**', article.content)  # no literal Markdown mixed into HTML

    def test_category_defaults_to_ticket_category_when_not_overridden(self):
        response = self.client.post(reverse('kb:convert_ticket', args=[self.ticket.pk]), {
            'title': 'How to fix VPN drops',
            'category': '',
            'visibility': 'INTERNAL',
            'include_comment': [],
        })
        article = Article.objects.get(title='How to fix VPN drops')
        self.assertEqual(article.category, self.ticket_category)

    def test_missing_resolution_steps_gets_editable_placeholder_not_bare_list(self):
        bare_ticket = Ticket.objects.create(
            type=Ticket.Type.INCIDENT,
            title='Printer offline',
            description='Printer shows offline.',
            requester=self.requester,
            number='TCK-BARE-001',
        )
        self.client.post(reverse('kb:convert_ticket', args=[bare_ticket.pk]), {
            'title': 'How to fix printer offline',
            'category': '',
            'visibility': 'INTERNAL',
            'include_comment': [],
        })
        article = Article.objects.get(title='How to fix printer offline')
        self.assertNotIn('1. \n2. \n3.', article.content)
        self.assertIn('describe the fix here', article.content)

    def test_conversation_summary_renders_as_real_html(self):
        comment = TicketComment.objects.create(
            ticket=self.ticket, author=self.agent, body='Tried restarting the router.', visibility='PUBLIC',
        )
        response = self.client.post(reverse('kb:convert_ticket', args=[self.ticket.pk]), {
            'title': 'How to fix VPN drops',
            'category': '',
            'visibility': 'INTERNAL',
            'include_comment': [str(comment.pk)],
        })
        article = Article.objects.get(title='How to fix VPN drops')
        self.assertIn('<strong>Conv Agent</strong>', article.content)
        self.assertIn('Tried restarting the router.', article.content)
        self.assertNotIn('**Conversation Summary**', article.content)


class KBSearchAndPortalTests(TestCase):
    """Full-text search ranking and category-card counts on the public
    portal, including the parent-category ("section") grouping."""

    def setUp(self):
        self.client = Client()
        self.author = User.objects.create_user(
            email='searchauthor@example.com', password='TestPass123!',
            first_name='Search', last_name='Author', department='IT',
            role=User.Role.AGENT, is_active=True, email_verified=True,
        )
        self.section = Category.objects.create(name='Getting Started', slug='getting-started')
        self.subcategory = Category.objects.create(name='Account Setup', slug='account-setup', parent=self.section)
        self.client.login(email='searchauthor@example.com', password='TestPass123!')

    def _published_article(self, title, content, category=None):
        article = Article.objects.create(
            title=title, slug=title.lower().replace(' ', '-'), content=content,
            category=category, author=self.author,
            status=Article.Status.PUBLISHED, visibility='PUBLIC',
        )
        return article

    def test_search_ranks_title_match_above_body_match(self):
        self._published_article('Resetting your password', '<p>General account help.</p>')
        self._published_article('General account help', '<p>Covers resetting your password among other things.</p>')
        response = self.client.get(reverse('kb:portal'), {'q': 'resetting your password'})
        titles = [a.title for a in response.context['articles']]
        self.assertEqual(titles[0], 'Resetting your password')

    def test_portal_shows_top_level_category_cards_with_counts(self):
        self._published_article('How to sign up', '<p>...</p>', category=self.subcategory)
        response = self.client.get(reverse('kb:portal'))
        cards = {c.pk: c for c in response.context['top_level_categories']}
        self.assertEqual(cards[self.section.pk].article_count, 1)
        self.assertEqual(cards[self.section.pk].section_count, 1)

    def test_selecting_top_level_category_includes_subcategory_articles(self):
        article = self._published_article('How to sign up', '<p>...</p>', category=self.subcategory)
        response = self.client.get(reverse('kb:portal'), {'category': self.section.pk})
        self.assertIn(article, response.context['articles'])

    def test_selecting_subcategory_filters_to_itself_only(self):
        in_sub = self._published_article('How to sign up', '<p>...</p>', category=self.subcategory)
        in_section_only = self._published_article('Section-level article', '<p>...</p>', category=self.section)
        response = self.client.get(reverse('kb:portal'), {'category': self.subcategory.pk})
        self.assertIn(in_sub, response.context['articles'])
        self.assertNotIn(in_section_only, response.context['articles'])
