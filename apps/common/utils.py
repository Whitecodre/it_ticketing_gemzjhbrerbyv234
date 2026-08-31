# apps/common/utils.py
import json, requests
import base64
import html as html_lib
import logging
import threading
from django.conf import settings
from django.db import transaction, close_old_connections
from pywebpush import webpush, WebPushException
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from .models import PushSubscription

logger = logging.getLogger(__name__)


def run_in_background(fn, *args, **kwargs):
    """Run fn(*args, **kwargs) in a daemon thread once the current DB
    transaction commits, so slow work (outbound email, etc.) never blocks
    the request/response cycle. Never pass a live HttpRequest into fn —
    build any URL/data it needs from the request first and pass plain
    values instead. Each thread gets its own DB connection, closed when
    the thread finishes so connections don't leak."""
    def _run():
        try:
            fn(*args, **kwargs)
        except Exception:
            logger.exception("Background task %s failed", getattr(fn, '__name__', fn))
        finally:
            close_old_connections()

    transaction.on_commit(lambda: threading.Thread(target=_run, daemon=True).start())

def resolve_sort(request, options, default_key, param='sort'):
    """Resolve a whitelisted `?sort=` GET param against a view-supplied
    options dict, for list views with a user-facing sort dropdown.

    options: {key: (order_by_args_tuple, label)}. An unrecognized/missing
    key silently falls back to default_key — user input is never passed
    into order_by() directly, only used to pick from a fixed whitelist.

    Returns (order_by_args, active_key, display_options) where
    display_options is a [(key, label), ...] list in dict-insertion order,
    ready to hand straight to components/sort_dropdown.html."""
    key = request.GET.get(param, default_key)
    if key not in options:
        key = default_key
    return options[key][0], key, [(k, v[1]) for k, v in options.items()]


def role_of(user):
    """The role name (string) a Notification.role should be tagged with for
    a given recipient/actor — their active role at this moment, so a dual-
    role account only sees the notification while wearing the matching hat.
    Returns None (role-agnostic) if the user has no role assigned at all."""
    if not user:
        return None
    active_role = user.get_active_role()
    return active_role.name if active_role else None


def notification_role_q(user):
    """Q object scoping a Notification queryset to `user`'s currently active
    role, plus role-agnostic (null-role) notifications, which always show
    regardless of active role. Combine with .filter(recipient=user, ...)."""
    from django.db.models import Q
    return Q(role=role_of(user)) | Q(role__isnull=True)


def send_push_notification(notification):
    """
    Send a push notification to all subscribers of the notification recipient.
    Returns a dict with counts: {'sent': int, 'failed': int, 'expired': int}
    """
    subscriptions = PushSubscription.objects.filter(user=notification.recipient)
    if not subscriptions:
        return {'sent': 0, 'failed': 0, 'expired': 0}

    # Prepare the data payload
    payload = json.dumps({
        'title': 'Gemz Software',
        'body': notification.message,
        'url': notification.url or '/',
    })

    # Decode private key if needed (if stored as base64)
    private_key = settings.VAPID_PRIVATE_KEY
    # Handle both raw base64 and PEM formats
    if private_key.startswith('LS0tLS1CRUdJTiB'):  # Base64 for '-----BEGIN'
        private_key = base64.b64decode(private_key).decode('utf-8')

    sent = 0
    failed = 0
    expired = 0

    for sub in subscriptions:
        try:
            webpush(
                subscription_info={
                    'endpoint': sub.endpoint,
                    'keys': {
                        'auth': sub.auth_key,
                        'p256dh': sub.p256dh_key,
                    }
                },
                data=payload,
                vapid_private_key=private_key,
                vapid_claims={
                    'sub': f'mailto:{settings.VAPID_CLAIM_EMAIL}'
                }
            )
            sent += 1
        except WebPushException as e:
            if e.response and e.response.status_code == 410:
                # Subscription expired – remove it
                sub.delete()
                expired += 1
            else:
                failed += 1
                logger.warning(f"Push failed for {sub.user.email}: {e}")

    return {'sent': sent, 'failed': failed, 'expired': expired}

def send_email_via_brevo(to_email, subject, html_content, from_email=None, template_data=None):
    """
    Send email via SMTP (Django's SMTP EmailBackend, using the
    EMAIL_HOST_USER/EMAIL_HOST_PASSWORD relay credentials in .env).

    The org's Brevo account was discontinued (updated org policy) and this
    now points at a different private-email SMTP provider — the
    Brevo-specific HTTP API fallback below is commented out (not deleted)
    since it's provider-specific and can't succeed against a non-Brevo
    account; restore it (and BREVO_API_KEY in .env/production.py) if this
    ever moves back to Brevo.
    """
    if not from_email:
        from_email = settings.DEFAULT_FROM_EMAIL

    # If template_data is provided, use it for variable substitution
    if template_data:
        html_content = render_to_string(html_content, template_data)

    # Django auto-escapes template variables (e.g. a password or name
    # containing '&', "'", etc. renders as '&amp;'/'&#x27;' in the HTML).
    # strip_tags() only removes tags, so without unescaping first, the
    # plain-text alternative would show those literal HTML entities instead
    # of the real characters — corrupting anything a recipient copies from
    # a text-preferring email client (most visibly, login passwords).
    plain_text = html_lib.unescape(strip_tags(html_content))

    try:
        msg = EmailMultiAlternatives(subject, plain_text, from_email, [to_email])
        msg.attach_alternative(html_content, "text/html")
        msg.send(fail_silently=False)
        logger.info(f"Email sent to {to_email} via SMTP")
        return True, "sent via SMTP"
    except Exception as smtp_error:
        logger.warning(f"SMTP send failed for {to_email}: {smtp_error}")
        # return _send_via_brevo_api(to_email, subject, html_content, plain_text, from_email)
        return False, str(smtp_error)


# --- Brevo HTTP Transactional API fallback — DISABLED (Brevo account
# discontinued per updated org policy). Kept commented out rather than
# deleted in case Brevo is reinstated later; see send_email_via_brevo above.
#
# def _send_via_brevo_api(to_email, subject, html_content, plain_text, from_email):
#     """Fallback path for send_email_via_brevo: Brevo's HTTP Transactional API."""
#     api_key = settings.BREVO_API_KEY
#
#     if not api_key:
#         logger.error("BREVO_API_KEY not configured in .env")
#         return False, "SMTP failed and BREVO_API_KEY not configured for fallback"
#
#     url = "https://api.brevo.com/v3/smtp/email"
#
#     payload = {
#         "sender": {"email": from_email, "name": "TicketSwipe"},
#         "to": [{"email": to_email}],
#         "subject": subject,
#         "htmlContent": html_content,
#         "textContent": plain_text,
#     }
#
#     headers = {
#         "accept": "application/json",
#         "content-type": "application/json",
#         "api-key": api_key,
#     }
#
#     try:
#         response = requests.post(url, json=payload, headers=headers, timeout=30)
#         response.raise_for_status()
#         result = response.json()
#         logger.info(f"Email sent to {to_email} via Brevo API (SMTP fallback)")
#         return True, result
#     except requests.exceptions.RequestException as e:
#         logger.error(f"Brevo API fallback also failed for {to_email}: {str(e)}")
#         if hasattr(e, 'response') and e.response:
#             logger.error(f"Response: {e.response.text}")
#         return False, str(e)


def send_email_brevo(to_email, subject, html_template, context_data, from_email=None):
    """
    Wrapper for sending templated emails — name kept as-is (send_email_brevo)
    since it's called from many sites; no longer Brevo-specific, just routes
    through send_email_via_brevo's plain-SMTP path.
    """
    html_content = render_to_string(html_template, context_data)
    return send_email_via_brevo(to_email, subject, html_content, from_email)


def notify_recipients_by_email(recipients, subject, message, url=None):
    """Send a plain-text-style HTML email to each of `recipients`, mirroring
    the message that already went out as an in-app Notification — used for
    alerts (low-stock, renewal-due) where push/in-app alone can be missed
    if nobody has a device subscribed or nobody is watching the app.
    Failures are logged, not raised — email is a supplementary channel
    here, not the primary one."""
    absolute_url = f"{settings.SITE_URL}{url}" if url and hasattr(settings, 'SITE_URL') else url
    link_html = f'<p><a href="{absolute_url}">View details</a></p>' if absolute_url else ''
    html_content = f'<p>{message}</p>{link_html}'
    for recipient in recipients:
        if not recipient.email:
            continue
        success, result = send_email_via_brevo(
            to_email=recipient.email,
            subject=subject,
            html_content=html_content,
        )
        if not success:
            logger.error(f"Failed to send alert email to {recipient.email}: {result}")