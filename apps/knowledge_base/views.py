import hashlib
import time
from datetime import date
from django.core.files.storage import default_storage
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.urls import reverse
from django.utils.text import slugify
from django.utils import timezone
from .models import Article, ArticleVersion, Category, ArticleFeedback
from .forms import ArticleMetadataForm, KBFromTicketForm
from .sanitize import sanitize_html
from django.core.paginator import Paginator
from django.db.models import Count, F, Q
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from apps.tickets.models import Ticket
from apps.common.models import Tag
from apps.tickets.views import get_sidebar_template
from apps.common.permissions import effective_role_name

# Images only, narrower than apps.tickets.views.ALLOWED_MIMES (documents
# aren't a valid KB article image) — same size cap as ticket attachments.
KB_IMAGE_ALLOWED_MIMES = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
KB_IMAGE_MAX_SIZE_MB = 10

# "Start from template" scaffold offered on article creation — a content
# pre-fill the author edits from, same mechanism convert_ticket_to_kb uses
# to seed a draft's initial HTML.
ARTICLE_TEMPLATE_SCAFFOLD = (
    '<h2>Overview</h2><p>Briefly describe what this article covers and who it\'s for.</p>'
    '<h2>Steps</h2><p>Walk through the steps in order.</p>'
    '<h2>Troubleshooting</h2><p>Common issues and how to resolve them.</p>'
    '<h2>Related Links</h2><p></p>'
)


@login_required
def kb_management(request):
    """Agent/TL/Admin view for managing KB articles."""
    user = request.user
    if effective_role_name(user) not in ('AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN') or user.department != 'IT':
        return HttpResponseForbidden()

    query = request.GET.get('q', '').strip()

    drafts_qs = Article.objects.filter(author=user, status=Article.Status.DRAFT).order_by('-updated_at')
    pending_qs = Article.objects.filter(status=Article.Status.PENDING_REVIEW).order_by('-updated_at') if user.role in ['TEAM_LEAD', 'ADMIN', 'SUPERADMIN'] else Article.objects.none()
    published_qs = Article.objects.filter(status=Article.Status.PUBLISHED).order_by('-updated_at')
    # Same visibility gate as Pending Review — archiving/restoring is
    # already TEAM_LEAD/ADMIN/SUPERADMIN-only, so only they need to see
    # what's sitting in the archive.
    archived_qs = Article.objects.filter(status=Article.Status.ARCHIVED).order_by('-updated_at') if user.role in ['TEAM_LEAD', 'ADMIN', 'SUPERADMIN'] else Article.objects.none()

    if query:
        title_or_content = Q(title__icontains=query) | Q(content__icontains=query) | Q(tags__name__icontains=query)
        drafts_qs = drafts_qs.filter(title_or_content).distinct()
        pending_qs = pending_qs.filter(title_or_content).distinct()
        published_qs = published_qs.filter(title_or_content).distinct()
        archived_qs = archived_qs.filter(title_or_content).distinct()

    # Each tab paginates independently so switching tabs (or paging one)
    # doesn't reset another — page params are namespaced per tab.
    drafts = Paginator(drafts_qs, 12).get_page(request.GET.get('drafts_page'))
    pending_review = Paginator(pending_qs, 12).get_page(request.GET.get('pending_page'))
    published = Paginator(published_qs, 12).get_page(request.GET.get('published_page'))
    archived = Paginator(archived_qs, 12).get_page(request.GET.get('archived_page'))

    sidebar_template = get_sidebar_template(user)

    context = {
        'drafts': drafts,
        'pending_review': pending_review,
        'published': published,
        'archived': archived,
        'search_query': query,
        'sidebar_template': sidebar_template,
        'categories': Category.objects.all(),
    }
    return render(request, 'knowledge_base/management.html', context)


@login_required
@require_POST
def article_create(request):
    """Step 1 of the article wizard: create a draft from title/category/
    visibility/tags (submitted via the metadata modal on the management
    page), then hand off to the content step. AJAX-only — the "New Article"
    button opens the modal client-side rather than navigating here."""
    if effective_role_name(request.user) not in ('AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN') or request.user.department != 'IT':
        return JsonResponse({'error': 'Forbidden'}, status=403)

    form = ArticleMetadataForm(request.POST)
    if not form.is_valid():
        return JsonResponse({'error': 'Invalid data', 'errors': form.errors}, status=400)

    title = form.cleaned_data['title']
    initial_content = ARTICLE_TEMPLATE_SCAFFOLD if request.POST.get('use_template') else ''
    article = Article(
        title=title,
        slug=slugify(title) + '-' + str(int(time.time())),
        content=initial_content,
        category=form.cleaned_data['category'],
        visibility=form.cleaned_data['visibility'],
        author=request.user,
        status=Article.Status.DRAFT,
    )
    article.save()
    tag_names = form.cleaned_data.get('tags_input') or []
    if tag_names:
        article.tags.set([Tag.objects.get_or_create(name=name)[0] for name in tag_names])

    ArticleVersion.objects.create(article=article, content=initial_content, edited_by=request.user)

    return JsonResponse({'status': 'ok', 'redirect': reverse('kb:edit_content', args=[article.pk])})


@login_required
@require_POST
def kb_image_upload(request):
    """Real image upload for the KB content editor — replaces the old
    URL-only / paste-as-base64 flow. Returns {"url": ...} for the editor to
    insert via setImage(). No DB row is created (unlike ticket Attachment,
    which needs an audit trail); this is a plain storage write."""
    if request.user.role not in ['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN']:
        return JsonResponse({'error': 'Forbidden'}, status=403)

    image = request.FILES.get('image')
    if not image:
        return JsonResponse({'error': 'No image provided.'}, status=400)
    if image.size > KB_IMAGE_MAX_SIZE_MB * 1024 * 1024:
        return JsonResponse({'error': f'Image exceeds {KB_IMAGE_MAX_SIZE_MB}MB limit.'}, status=400)
    mime = (image.content_type or '').split(';')[0].strip().lower()
    if mime not in KB_IMAGE_ALLOWED_MIMES:
        return JsonResponse({'error': 'Unsupported image type.'}, status=400)

    ext = image.name.rsplit('.', 1)[-1].lower() if '.' in image.name else 'png'
    name_hash = hashlib.sha256(f'{image.name}{time.time()}'.encode()).hexdigest()[:16]
    saved_name = default_storage.save(f'kb_images/{timezone.now():%Y/%m/%d}/{name_hash}.{ext}', image)
    return JsonResponse({'url': default_storage.url(saved_name), 'alt': image.name})


@login_required
@require_POST
def article_metadata_update(request, pk):
    """AJAX endpoint backing the "Edit Details" modal on the content step —
    updates title/category/visibility/tags without touching content."""
    article = get_object_or_404(Article, pk=pk)
    if request.user != article.author and request.user.role not in ['TEAM_LEAD', 'ADMIN', 'SUPERADMIN']:
        return JsonResponse({'error': 'Forbidden'}, status=403)

    form = ArticleMetadataForm(request.POST, instance=article)
    if not form.is_valid():
        return JsonResponse({'error': 'Invalid data', 'errors': form.errors}, status=400)
    form.save()
    return JsonResponse({'status': 'ok', 'title': article.title})


@login_required
def article_edit_content(request, pk):
    """Step 2 of the article wizard: the content-only page with the TipTap
    editor. Metadata (title/category/visibility/tags) is edited inline here
    via the same modal used at creation, through article_metadata_update."""
    article = get_object_or_404(Article, pk=pk)
    if request.user != article.author and request.user.role not in ['TEAM_LEAD', 'ADMIN', 'SUPERADMIN']:
        return HttpResponseForbidden()

    if request.method == 'POST':
        article.content = sanitize_html(request.POST.get('content', ''))
        article.save()
        ArticleVersion.objects.create(article=article, content=article.content, edited_by=request.user)
        messages.success(request, f'Article "{article.title}" updated.')
        return redirect('kb:management')

    context = {
        'article': article,
        'metadata_form': ArticleMetadataForm(instance=article),
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'knowledge_base/article_content_edit.html', context)


@login_required
@require_POST
def article_submit_review(request, pk):
    article = get_object_or_404(Article, pk=pk)
    if request.user != article.author:
        return HttpResponseForbidden()
    article.status = Article.Status.PENDING_REVIEW
    article.save()
    messages.success(request, f'Article "{article.title}" submitted for review.')
    return redirect('kb:management')


@login_required
@require_POST
def article_publish(request, pk):
    article = get_object_or_404(Article, pk=pk)
    if request.user.role not in ['TEAM_LEAD', 'ADMIN', 'SUPERADMIN']:
        return HttpResponseForbidden()
    if article.status != Article.Status.PENDING_REVIEW:
        messages.error(request, 'Only articles pending review can be published.')
        return redirect('kb:management')
    article.status = Article.Status.PUBLISHED
    if not article.published_at:
        article.published_at = timezone.now()
        article.published_by = request.user
    article.save()
    messages.success(request, f'Article "{article.title}" published.')
    return redirect('kb:management')


@login_required
@require_POST
def article_archive(request, pk):
    article = get_object_or_404(Article, pk=pk)
    if request.user.role not in ['TEAM_LEAD', 'ADMIN', 'SUPERADMIN']:
        return HttpResponseForbidden()
    article.archived_from_status = article.status
    article.status = Article.Status.ARCHIVED
    article.save()
    messages.success(request, f'Article "{article.title}" archived.')
    return redirect('kb:management')


@login_required
@require_POST
def article_restore(request, pk):
    """Undo an archive — puts the article back in whatever status it was
    in right before it was archived (Published stays Published, Draft
    stays Draft), instead of always dumping it into Draft."""
    article = get_object_or_404(Article, pk=pk)
    if request.user.role not in ['TEAM_LEAD', 'ADMIN', 'SUPERADMIN']:
        return HttpResponseForbidden()
    if article.status != Article.Status.ARCHIVED:
        messages.error(request, 'Only archived articles can be restored.')
        return redirect('kb:management')
    article.status = article.archived_from_status or Article.Status.DRAFT
    article.archived_from_status = None
    article.save()
    messages.success(request, f'Article "{article.title}" restored to {article.get_status_display()}.')
    return redirect('kb:management')


@login_required
@require_POST
def article_delete(request, pk):
    """Permanently remove a draft — the author's own, or any Lead/Admin's.
    Only DRAFT articles are deletable this way; anything that's been
    through review at least once (Pending/Published/Archived) goes through
    Archive instead, which keeps its history rather than erasing it."""
    article = get_object_or_404(Article, pk=pk)
    if article.status != Article.Status.DRAFT:
        messages.error(request, 'Only drafts can be deleted — archive published or reviewed articles instead.')
        return redirect('kb:management')
    if article.author_id != request.user.pk and request.user.role not in ['TEAM_LEAD', 'ADMIN', 'SUPERADMIN']:
        return HttpResponseForbidden()
    title = article.title
    article.delete()
    messages.success(request, f'"{title}" was deleted.')
    return redirect('kb:management')


@login_required
@require_POST
def article_reject_review(request, pk):
    """Send a PENDING_REVIEW article back to DRAFT for the author to revise
    — distinct from Archive, which retires an article rather than returning
    it for more work."""
    article = get_object_or_404(Article, pk=pk)
    if request.user.role not in ['TEAM_LEAD', 'ADMIN', 'SUPERADMIN']:
        return HttpResponseForbidden()
    if article.status != Article.Status.PENDING_REVIEW:
        messages.error(request, 'Only articles pending review can be sent back.')
        return redirect('kb:management')

    reason = request.POST.get('reason', '').strip()
    article.status = Article.Status.DRAFT
    article.save()

    from apps.common.models import Notification
    from apps.common.utils import role_of
    note = f'"{article.title}" was sent back to draft by {request.user.get_full_name()}.'
    if reason:
        note += f' Reason: {reason}'
    Notification.objects.create(
        recipient=article.author,
        role=role_of(article.author),
        message=note,
        url=reverse('kb:edit_content', args=[article.pk]),
        type=Notification.Type.GENERAL,
    )

    messages.success(request, f'"{article.title}" was sent back to the author for revisions.')
    return redirect('kb:management')

@login_required
def kb_portal(request):
    query = request.GET.get('q', '')
    category_id = request.GET.get('category', '')
    tag_name = request.GET.get('tag', '')

    articles = Article.objects.filter(status=Article.Status.PUBLISHED, visibility='PUBLIC')

    if query:
        from django.contrib.postgres.search import SearchVector, SearchQuery, SearchRank
        search_query = SearchQuery(query)
        vector = SearchVector('title', weight='A') + SearchVector('content', weight='B')
        articles = articles.annotate(search=vector, rank=SearchRank(vector, search_query)).filter(
            Q(search=search_query) | Q(tags__name__icontains=query)
        ).distinct().order_by('-rank')

    selected_category = None
    if category_id:
        selected_category = Category.objects.filter(pk=category_id).first()
        if selected_category:
            # A top-level category (a "section") shows articles from itself
            # AND its children; a child category filters to just itself.
            if selected_category.parent_id is None:
                articles = articles.filter(
                    Q(category=selected_category) | Q(category__parent=selected_category)
                )
            else:
                articles = articles.filter(category=selected_category)

    if tag_name:
        articles = articles.filter(tags__name=tag_name)

    # Top-level categories ("sections") as cards, each showing how many
    # published/public articles it (and its subcategories) contain, and how
    # many subcategories it has — mirrors a "Articles N / Sections N" card.
    # article_count is computed per-category in Python rather than as a
    # single combined SQL annotation: summing two Count()s that join through
    # different relations (articles vs children__articles) in one query
    # multiplies rows across the joins and silently over-counts.
    top_level_categories = list(
        Category.objects.filter(parent__isnull=True).annotate(section_count=Count('children', distinct=True)).order_by('name')
    )
    for cat in top_level_categories:
        cat.article_count = Article.objects.filter(
            Q(category=cat) | Q(category__parent=cat),
            status=Article.Status.PUBLISHED, visibility='PUBLIC',
        ).count()

    subcategories = Category.objects.none()
    if selected_category and selected_category.parent_id is None:
        subcategories = selected_category.children.annotate(
            article_count=Count('articles', filter=Q(articles__status=Article.Status.PUBLISHED, articles__visibility='PUBLIC'))
        )

    # All tags with counts (for filtering)
    all_tags = Tag.objects.filter(
        article__status=Article.Status.PUBLISHED,
        article__visibility='PUBLIC'
    ).annotate(
        count=Count('article')
    ).order_by('name')

    # The Article Grid is for browsing/filter RESULTS — only show it once the
    # user is actually searching, has picked a category, or picked a tag.
    # Otherwise (bare landing page) `articles` is still every published/public
    # article in the whole KB, which used to render as stray cards under the
    # category-folder grid instead of staying hidden until a filter is chosen.
    show_articles = bool(query or selected_category or tag_name)

    # "Popular guides" strip on the bare landing page — ranked by actual
    # view_count (bumped in kb_article_detail), not insertion order. Only
    # worth showing once the library has enough articles for the ranking to
    # mean anything.
    popular_articles = []
    if not query and not selected_category:
        base_articles = Article.objects.filter(status=Article.Status.PUBLISHED, visibility='PUBLIC')
        if base_articles.count() > 2:
            popular_articles = list(base_articles.order_by('-view_count', '-created_at')[:3])

    # Only categories that actually have a published/public article — the
    # template used to filter these out with an {% if %} inside the loop,
    # which meant Django's {% empty %} never fired (the loop itself wasn't
    # empty, just every row got hidden), leaving a blank "Browse by topic"
    # grid with no articles-yet message whenever every category was empty.
    visible_top_level_categories = [cat for cat in top_level_categories if cat.article_count]

    context = {
        'articles': articles,
        'show_articles': show_articles,
        'popular_articles': popular_articles,
        'top_level_categories': visible_top_level_categories,
        'subcategories': subcategories,
        'selected_category': selected_category,
        'all_tags': all_tags,
        'query': query,
        'selected_tag': tag_name,
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'knowledge_base/portal.html', context)

@login_required
def kb_article_detail(request, slug):
    # KB staff can read any published article regardless of visibility;
    # everyone else is restricted to PUBLIC — INTERNAL articles were
    # previously unreachable here even for staff.
    is_kb_staff = request.user.role in ['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN']
    if is_kb_staff:
        article = get_object_or_404(Article, slug=slug, status=Article.Status.PUBLISHED)
    else:
        article = get_object_or_404(Article, slug=slug, status=Article.Status.PUBLISHED, visibility='PUBLIC')

    # Atomic increment (not a read-modify-write on `article`) so concurrent
    # viewers don't clobber each other's count.
    Article.objects.filter(pk=article.pk).update(view_count=F('view_count') + 1)

    # Check if user already gave feedback
    user_feedback = None
    if request.user.is_authenticated:
        try:
            user_feedback = ArticleFeedback.objects.get(article=article, user=request.user)
        except ArticleFeedback.DoesNotExist:
            pass
    context = {
        'article': article,
        'user_feedback': user_feedback,
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'knowledge_base/article_detail.html', context)

@login_required
@require_POST
def kb_feedback(request, pk):
    article = get_object_or_404(Article, pk=pk)
    helpful = request.POST.get('helpful') == 'true'
    feedback, created = ArticleFeedback.objects.update_or_create(
        article=article,
        user=request.user,
        defaults={'helpful': helpful}
    )
    helpful_count = article.feedback.filter(helpful=True).count()
    not_helpful_count = article.feedback.filter(helpful=False).count()
    return JsonResponse({
        'status': 'ok',
        'helpful_count': helpful_count,
        'not_helpful_count': not_helpful_count,
    })


def _escape_html(text):
    from django.utils.html import escape
    return escape(text or '')


def _build_ticket_scaffold_html(ticket):
    """Real HTML scaffold (not the old literal `**bold**`-in-HTML mix) —
    Original Issue / Root Cause / Resolution Steps, with an explicit
    editable placeholder when the ticket never recorded resolution steps."""
    parts = [
        '<h3>Original Issue</h3>',
        f'<p>{_escape_html(ticket.description)}</p>',
    ]
    if ticket.resolution_root_cause:
        parts.append('<h3>Root Cause</h3>')
        parts.append(f'<p>{_escape_html(ticket.resolution_root_cause)}</p>')
    parts.append('<h3>Resolution Steps</h3>')
    if ticket.resolution_steps:
        parts.append(f'<p>{_escape_html(ticket.resolution_steps)}</p>')
    else:
        parts.append(
            '<div class="kb-callout"><p><em>No resolution steps were recorded on the ticket — '
            'describe the fix here before publishing.</em></p></div>'
        )
    parts.append('<h3>Additional Notes</h3><p></p>')
    return ''.join(parts)


def _build_conversation_summary_html(comments):
    """Selected ticket comments as real HTML, appended to the scaffold —
    previously built with literal Markdown (**bold**) mixed into HTML."""
    if not comments:
        return ''
    parts = ['<hr><h3>Conversation Summary</h3>']
    for comment in comments:
        parts.append(
            f'<p><strong>{_escape_html(comment.author.get_full_name())}</strong> '
            f'({comment.created_at.strftime("%b %d, %Y %H:%M")}):</p>'
            f'<p>{_escape_html(comment.body)}</p>'
        )
    return ''.join(parts)


@login_required
def convert_ticket_to_kb(request, ticket_pk):
    """Metadata-only step: title/category/visibility/which comments to
    include. Save creates a DRAFT article (content = a scaffold built from
    the ticket) and redirects into kb:edit_content — the same TipTap editor
    every other article uses — for the agent to actually write/refine it."""
    ticket = get_object_or_404(Ticket, pk=ticket_pk)

    if request.user.role not in ['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN']:
        return HttpResponseForbidden("You don't have permission to create KB articles.")

    if request.method == 'POST':
        form = KBFromTicketForm(ticket, request.POST)
        if form.is_valid():
            title = form.cleaned_data['title']
            visibility = form.cleaned_data['visibility']
            selected_comment_ids = form.cleaned_data.get('include_comment', [])

            content = _build_ticket_scaffold_html(ticket)
            if selected_comment_ids:
                selected_comments = ticket.comments.filter(pk__in=selected_comment_ids).order_by('created_at')
                content += _build_conversation_summary_html(selected_comments)
            content = sanitize_html(content)

            slug = slugify(title) + '-' + str(int(time.time()))
            article = Article.objects.create(
                title=title,
                slug=slug,
                content=content,
                category=form.cleaned_data.get('category') or ticket.category,
                visibility=visibility,
                author=request.user,
                status=Article.Status.DRAFT,
            )
            ArticleVersion.objects.create(article=article, content=content, edited_by=request.user)

            messages.success(request, f'"{title}" created as a draft — refine and save it below.')
            return redirect('kb:edit_content', pk=article.pk)
    else:
        form = KBFromTicketForm(
            ticket=ticket,
            initial={
                'title': f"How to resolve: {ticket.title}",
                'category': ticket.category,
                'visibility': 'INTERNAL',
            }
        )

    context = {
        'form': form,
        'ticket': ticket,
        'sidebar_template': get_sidebar_template(request.user),
        'ticket_status': ticket.get_status_display(),
    }
    return render(request, 'knowledge_base/create_from_ticket.html', context)

# apps/knowledge_base/views.py

@login_required
def kb_suggestions_ajax(request):
    """
    HTMX endpoint to return article suggestions based on a query.
    Used during ticket creation to show relevant articles.
    """
    # Check both 'title' and 'q' parameters (for compatibility)
    query = request.GET.get('title', '') or request.GET.get('q', '')
    query = query.strip()
    
    # Only search if query is at least 2 characters
    if len(query) < 2:
        return render(request, 'partials/kb_suggestions.html', {'articles': []})
    
    # Search published, public articles — full-text ranked (title weighted
    # above content), same approach as kb_portal's search.
    from django.contrib.postgres.search import SearchVector, SearchQuery, SearchRank
    search_query = SearchQuery(query)
    vector = SearchVector('title', weight='A') + SearchVector('content', weight='B')
    articles = Article.objects.filter(
        status=Article.Status.PUBLISHED,
        visibility='PUBLIC'
    ).annotate(search=vector, rank=SearchRank(vector, search_query)).filter(
        search=search_query
    ).order_by('-rank', '-updated_at')[:5]

    return render(request, 'partials/kb_suggestions.html', {'articles': articles})


@login_required
def kb_composer_search(request):
    """HTMX endpoint backing the "Insert KB Article" control in the ticket
    reply composer (templates/agent/ticket_conversation.html). Scoped to
    published + public articles only, same as kb_suggestions_ajax — a
    composer message can be sent publicly, so nothing internal-only should
    be offered here."""
    query = request.GET.get('q', '').strip()

    if len(query) < 2:
        return render(request, 'partials/kb_composer_results.html', {'articles': []})

    from django.contrib.postgres.search import SearchVector, SearchQuery, SearchRank
    search_query = SearchQuery(query)
    vector = SearchVector('title', weight='A') + SearchVector('content', weight='B')
    articles = Article.objects.filter(
        status=Article.Status.PUBLISHED,
        visibility='PUBLIC'
    ).annotate(search=vector, rank=SearchRank(vector, search_query)).filter(
        search=search_query
    ).order_by('-rank', '-updated_at')[:8]

    return render(request, 'partials/kb_composer_results.html', {'articles': articles})


@login_required
def article_history(request, pk):
    """
    Display the version history of an article.
    Only accessible to agents, team leads, admins, and superadmins.
    """
    article = get_object_or_404(Article, pk=pk)
    
    # Permission: only users who can edit the article can view history
    if request.user.role not in ['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN']:
        return HttpResponseForbidden("You don't have permission to view article history.")
    
    # If the article is a draft and the user is not the author (and not admin/lead), deny
    if article.status == Article.Status.DRAFT and request.user != article.author and request.user.role not in ['TEAM_LEAD', 'ADMIN', 'SUPERADMIN']:
        return HttpResponseForbidden("You can only view history of your own drafts.")
    
    versions = article.versions.all().order_by('-created_at')
    
    context = {
        'article': article,
        'versions': versions,
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'knowledge_base/article_history.html', context)


@login_required
def article_version_detail(request, pk, version_pk):
    """
    Return the content of a specific version (for preview modal).
    """
    article = get_object_or_404(Article, pk=pk)
    version = get_object_or_404(ArticleVersion, pk=version_pk, article=article)
    
    # Permission check
    if request.user.role not in ['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN']:
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    return JsonResponse({
        'content': version.content,
        'edited_by': version.edited_by.get_full_name(),
        'created_at': version.created_at.strftime('%Y-%m-%d %H:%M'),
    })


@login_required
@require_POST
def article_revert(request, pk, version_pk):
    """
    Revert the article to a previous version.
    Only team leads, admins, and superadmins can revert.
    """
    article = get_object_or_404(Article, pk=pk)
    
    # Only team leads, admins, superadmins can revert (or the author if draft? but we'll restrict)
    if request.user.role not in ['TEAM_LEAD', 'ADMIN', 'SUPERADMIN']:
        return HttpResponseForbidden("Only team leads and admins can revert articles.")
    
    version = get_object_or_404(ArticleVersion, pk=version_pk, article=article)
    
    # Store the old content for audit (we'll create a new version anyway)
    old_content = article.content
    
    # Revert: set article content to version content. Sanitized again here
    # (not just at write time) as defense-in-depth for any ArticleVersion
    # rows created before sanitization was added.
    article.content = sanitize_html(version.content)
    article.save()
    
    # Create a new version entry with a note
    ArticleVersion.objects.create(
        article=article,
        content=article.content,
        edited_by=request.user,
    )
    
    # Optionally, add a note to the article (you could store this in a separate field)
    # We'll just log it via messages and version creation (the new version has the editor)
    
    messages.success(request, f'Article "{article.title}" has been reverted to the version from {version.created_at.strftime("%b %d, %Y")}.')
    
    return redirect('kb:management')


@login_required
def tag_autocomplete(request):
    """
    Return a JSON list of tag names matching the query for autocomplete.
    """
    query = request.GET.get('q', '').strip()
    if len(query) < 1:
        return JsonResponse([], safe=False)
    
    tags = Tag.objects.filter(name__icontains=query).values_list('name', flat=True)[:10]
    return JsonResponse(list(tags), safe=False)