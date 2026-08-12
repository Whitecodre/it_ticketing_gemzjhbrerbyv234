import time
from datetime import date
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.urls import reverse
from django.utils.text import slugify
from .models import Article, ArticleVersion, Category, ArticleFeedback
from .forms import ArticleForm, KBFromTicketForm
from django.db.models import Count, Q
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from apps.tickets.models import Ticket
from apps.common.models import Tag
from apps.tickets.views import get_sidebar_template


@login_required
def kb_management(request):
    """Agent/TL/Admin view for managing KB articles."""
    user = request.user
    if user.role not in ['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN']:
        return HttpResponseForbidden()

    drafts = Article.objects.filter(author=user, status=Article.Status.DRAFT)
    pending_review = Article.objects.filter(status=Article.Status.PENDING_REVIEW) if user.role in ['TEAM_LEAD', 'ADMIN', 'SUPERADMIN'] else []
    published = Article.objects.filter(status=Article.Status.PUBLISHED)

    # Choose sidebar based on role
    sidebar_map = {
        'AGENT': 'partials/sidebar_agent.html',
        'TEAM_LEAD': 'partials/sidebar_team_lead.html',
        'ADMIN': 'partials/sidebar_admin.html',
        'SUPERADMIN': 'partials/sidebar_superadmin.html',  
    }
    sidebar_template = sidebar_map.get(user.role, 'partials/sidebar_agent.html')

    context = {
        'drafts': drafts,
        'pending_review': pending_review,
        'published': published,
        'sidebar_template': sidebar_template,
    }
    return render(request, 'knowledge_base/management.html', context)


@login_required
def article_create(request):
    """Create a new article draft with rich text editor."""
    if request.user.role not in ['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN']:
        return HttpResponseForbidden()

    if request.method == 'POST':
        form = ArticleForm(request.POST)
        if form.is_valid():
            # Create the article manually
            title = form.cleaned_data['title']
            content = form.cleaned_data['content']
            category = form.cleaned_data['category']
            visibility = form.cleaned_data['visibility']
            tags_input = form.cleaned_data.get('tags_input', [])
            
            # Create article
            article = Article.objects.create(
                title=title,
                slug=slugify(title) + '-' + str(int(time.time())),
                content=content,
                category=category,
                visibility=visibility,
                author=request.user,
                status=Article.Status.DRAFT
            )
            
            # Handle tags
            if tags_input:
                tag_objects = []
                for name in tags_input:
                    tag, created = Tag.objects.get_or_create(name=name)
                    tag_objects.append(tag)
                article.tags.set(tag_objects)
            
            # Create version
            ArticleVersion.objects.create(
                article=article,
                content=article.content,
                edited_by=request.user
            )
            
            from django.contrib import messages
            messages.success(request, f'Article "{article.title}" created as a draft.')
            return redirect('kb:management')
        else:
            from django.contrib import messages
            messages.error(request, 'Please correct the errors below.')
    else:
        form = ArticleForm()

    context = {
        'form': form,
        'article': None,
        'sidebar_template': get_sidebar_template(request.user),
        'is_create': True,
    }
    return render(request, 'knowledge_base/article_form.html', context)


@login_required
def article_edit(request, pk):
    """Edit an existing draft with rich text editor."""
    article = get_object_or_404(Article, pk=pk)
    if request.user != article.author and request.user.role not in ['TEAM_LEAD', 'ADMIN', 'SUPERADMIN']:
        return HttpResponseForbidden()

    if request.method == 'POST':
        form = ArticleForm(request.POST, instance=article)
        if form.is_valid():
            article = form.save()
            ArticleVersion.objects.create(
                article=article,
                content=article.content,
                edited_by=request.user
            )
            from django.contrib import messages
            messages.success(request, f'Article "{article.title}" updated.')
            return redirect('kb:management')
    else:
        form = ArticleForm(instance=article)

    context = {
        'form': form,
        'article': article,
        'sidebar_template': get_sidebar_template(request.user),
        'is_create': False,
    }
    return render(request, 'knowledge_base/article_form.html', context)


@login_required
def article_submit_review(request, pk):
    article = get_object_or_404(Article, pk=pk)
    if request.user != article.author:
        return HttpResponseForbidden()
    article.status = Article.Status.PENDING_REVIEW
    article.save()
    return redirect('kb:management')


@login_required
def article_publish(request, pk):
    article = get_object_or_404(Article, pk=pk)
    if request.user.role not in ['TEAM_LEAD', 'ADMIN', 'SUPERADMIN']:
        return HttpResponseForbidden()
    article.status = Article.Status.PUBLISHED
    article.save()
    return redirect('kb:management')


@login_required
def article_archive(request, pk):
    article = get_object_or_404(Article, pk=pk)
    if request.user.role not in ['TEAM_LEAD', 'ADMIN', 'SUPERADMIN']:
        return HttpResponseForbidden()
    article.status = Article.Status.ARCHIVED
    article.save()
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
    note = f'📝 "{article.title}" was sent back to draft by {request.user.get_full_name()}.'
    if reason:
        note += f' Reason: {reason}'
    Notification.objects.create(
        recipient=article.author,
        message=note,
        url=reverse('kb:edit', args=[article.pk]),
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
        articles = articles.filter(
            Q(title__icontains=query) |
            Q(content__icontains=query) |
            Q(tags__name__icontains=query)  # Search tags
        ).distinct()
    
    if category_id:
        articles = articles.filter(category_id=category_id)
    
    if tag_name:
        articles = articles.filter(tags__name=tag_name)
    
    # Get categories with counts
    categories = Category.objects.annotate(
        article_count=Count('articles', filter=Q(articles__status=Article.Status.PUBLISHED, articles__visibility='PUBLIC'))
    )
    
    # Get all tags with counts (for filtering)
    all_tags = Tag.objects.filter(
        article__status=Article.Status.PUBLISHED,
        article__visibility='PUBLIC'
    ).annotate(
        count=Count('article')
    ).order_by('name')
    
    context = {
        'articles': articles,
        'categories': categories,
        'all_tags': all_tags,
        'query': query,
        'selected_category': category_id,
        'selected_tag': tag_name,
    }
    return render(request, 'knowledge_base/portal.html', context)

@login_required
def kb_article_detail(request, slug):
    article = get_object_or_404(Article, slug=slug, status=Article.Status.PUBLISHED, visibility='PUBLIC')
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


@login_required
def convert_ticket_to_kb(request, ticket_pk):
    ticket = get_object_or_404(Ticket, pk=ticket_pk)
    
    if request.user.role not in ['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN']:
        return HttpResponseForbidden("You don't have permission to create KB articles.")
    
    if request.method == 'POST':
        form = KBFromTicketForm(ticket, request.POST)
        if form.is_valid():
            title = form.cleaned_data['title']
            content = form.cleaned_data['content']
            visibility = form.cleaned_data['visibility']
            selected_comment_ids = form.cleaned_data.get('include_comment', [])
            
            # Build conversation summary
            if selected_comment_ids:
                selected_comments = ticket.comments.filter(pk__in=selected_comment_ids).order_by('created_at')
                conversation_summary = "\n\n---\n\n**Conversation Summary**\n\n"
                for comment in selected_comments:
                    conversation_summary += f"**{comment.author.get_full_name()}** ({comment.created_at.strftime('%b %d, %Y %H:%M')}):\n{comment.body}\n\n"
                final_content = content + conversation_summary
            else:
                final_content = content
            
            # Create article
            slug = slugify(title) + '-' + str(int(time.time()))
            article = Article.objects.create(
                title=title,
                slug=slug,
                content=final_content,
                category=ticket.category,
                visibility=visibility,
                author=request.user,
                status=Article.Status.DRAFT
            )
            ArticleVersion.objects.create(article=article, content=final_content, edited_by=request.user)
            
            from django.contrib import messages
            messages.success(request, f'Article "{title}" created as a draft.')
            return redirect('kb:management')
    else:
        initial_content = f"**Original Issue:**\n{ticket.description}\n\n"
        initial_content += "**Resolution Steps:**\n\n1. \n2. \n3. \n\n**Additional Notes:**\n\n"
        
        form = KBFromTicketForm(
            ticket=ticket,
            initial={
                'title': f"How to resolve: {ticket.title}",
                'content': initial_content,
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
    
    # Search published, public articles
    articles = Article.objects.filter(
        status=Article.Status.PUBLISHED,
        visibility='PUBLIC'
    ).filter(
        Q(title__icontains=query) | Q(content__icontains=query)
    ).annotate(
        title_match=Q(title__icontains=query)
    ).order_by('-title_match', '-updated_at')[:5]
    
    return render(request, 'partials/kb_suggestions.html', {'articles': articles})


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
    
    # Revert: set article content to version content
    article.content = version.content
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


def tag_autocomplete(request):
    """
    Return a JSON list of tag names matching the query for autocomplete.
    """
    query = request.GET.get('q', '').strip()
    if len(query) < 1:
        return JsonResponse([], safe=False)
    
    tags = Tag.objects.filter(name__icontains=query).values_list('name', flat=True)[:10]
    return JsonResponse(list(tags), safe=False)