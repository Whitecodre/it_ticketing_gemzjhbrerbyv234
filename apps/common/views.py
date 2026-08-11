import json, os
from django.conf import settings
from django.shortcuts import render
from django.http import HttpResponse, JsonResponse, FileResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.middleware.csrf import get_token
from django.core.paginator import Paginator
from .models import Notification, PushSubscription
from .utils import send_push_notification


def _get_sidebar_template(user):
    """Returns the correct sidebar partial based on user's active role."""
    mapping = {
        'END_USER': 'partials/sidebar_end_user.html',
        'AGENT': 'partials/sidebar_agent.html',
        'TEAM_LEAD': 'partials/sidebar_team_lead.html',
        'ADMIN': 'partials/sidebar_admin.html',
        'SUPERADMIN': 'partials/sidebar_superadmin.html',
    }
    active_role = user.get_active_role()
    role_name = active_role.name if active_role else user.role
    return mapping.get(role_name, 'partials/sidebar_end_user.html')



@login_required
@csrf_exempt
def test_push(request):
    """Debug endpoint to send a test push notification to the current user."""
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Not authorized'}, status=403)

    # Check if user has a subscription
    subscription = PushSubscription.objects.filter(user=request.user).first()
    if not subscription:
        return JsonResponse({'error': 'No push subscription found for this user'}, status=400)

    # Create a temporary notification (not saved) or use an existing one
    # For testing, we'll send a custom payload
    from django.utils import timezone
    test_notification = Notification(
        recipient=request.user,
        message='🔔 This is a test push notification!',
        url='/',
        created_at=timezone.now(),
    )

    result = send_push_notification(test_notification)
    return JsonResponse({
        'status': 'ok',
        'result': result,
        'message': f"Sent to {result['sent']} device(s).",
    })


@login_required
def unread_count(request):
    count = Notification.objects.filter(recipient=request.user, is_read=False).count()
    return render(request, 'partials/notification_badge.html', {'count': count})

@login_required
@require_POST
def mark_all_read(request):
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    # After marking all as read, count is always 0 → badge will be hidden
    return render(request, 'partials/notification_badge.html', {'count': 0})

@login_required
@require_POST
def mark_read(request, pk):
    try:
        notification = Notification.objects.get(pk=pk, recipient=request.user)
        notification.is_read = True
        notification.save()
        return JsonResponse({'status': 'ok'})
    except Notification.DoesNotExist:
        return JsonResponse({'status': 'error'}, status=404)
    
@login_required
def list_notifications(request):
    # Get all notifications for the user, newest first
    all_notifications = Notification.objects.filter(recipient=request.user).order_by('-created_at')
    unread = all_notifications.filter(is_read=False).count()
    notifications = all_notifications[:10]   # slice after counting
    return render(request, 'partials/notification_dropdown.html', {
        'notifications': notifications,
        'unread': unread,
        'csrf_token': get_token(request),
    })


@login_required
def notifications_page(request):
    """Full notifications page ('View all' destination) — not to be confused
    with list_notifications, which renders the bell dropdown fragment and is
    fetched via HTMX from several places; this is a real, standalone page."""
    notifications_qs = Notification.objects.filter(recipient=request.user).order_by('-created_at')

    filter_value = request.GET.get('filter', 'all')
    if filter_value == 'unread':
        notifications_qs = notifications_qs.filter(is_read=False)

    unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()

    paginator = Paginator(notifications_qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'notifications/list.html', {
        'notifications': page_obj,
        'unread_count': unread_count,
        'filter_value': filter_value,
        'sidebar_template': _get_sidebar_template(request.user),
    })

# WEBSOCKET INITIALIZATON
@login_required
def websocket_init_data(request):
    """Returns data needed to initialize the WebSocket connection."""
    unread_count = Notification.objects.filter(
        recipient=request.user,
        is_read=False
    ).count()
    return JsonResponse({
        'unread_count': unread_count,
        'websocket_url': '/ws/notifications/',
    })

@login_required
@csrf_exempt
@require_POST
def save_push_subscription(request):
    try:
        data = json.loads(request.body)
        endpoint = data.get('endpoint')
        auth_key = data.get('keys', {}).get('auth')
        p256dh_key = data.get('keys', {}).get('p256dh')

        if not endpoint or not auth_key or not p256dh_key:
            return JsonResponse({'error': 'Missing fields'}, status=400)

        subscription, created = PushSubscription.objects.update_or_create(
            user=request.user,
            endpoint=endpoint,
            defaults={
                'auth_key': auth_key,
                'p256dh_key': p256dh_key,
            }
        )
        return JsonResponse({'status': 'ok'})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@csrf_exempt
@require_POST
def delete_push_subscription(request):
    try:
        data = json.loads(request.body)
        endpoint = data.get('endpoint')
        if endpoint:
            PushSubscription.objects.filter(user=request.user, endpoint=endpoint).delete()
        return JsonResponse({'status': 'ok'})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

def service_worker(request):
    file_path = os.path.join(settings.STATIC_ROOT, 'sw.js')
    if not os.path.exists(file_path):
        # Fallback to static directory
        file_path = os.path.join(settings.BASE_DIR, 'static', 'sw.js')
    return FileResponse(open(file_path, 'rb'), content_type='application/javascript')


def ratelimit_handler(request, exception):
    """Custom handler for rate limit exceeded."""
    if request.headers.get('HX-Request'):
        return HttpResponse(
            'Too many login attempts. Please try again later.',
            status=429
        )
    return render(request, 'registration/rate_limited.html', status=429)