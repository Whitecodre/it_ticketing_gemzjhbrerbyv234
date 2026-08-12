# apps/common/utils.py
import json, requests
import base64
import html as html_lib
from django.conf import settings
from pywebpush import webpush, WebPushException
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from .models import PushSubscription

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
                # Log error (optional)
                print(f"Push failed for {sub.user.email}: {e}")

    return {'sent': sent, 'failed': failed, 'expired': expired}

def send_email_via_brevo(to_email, subject, html_content, from_email=None, template_data=None):
    """
    Send email via Brevo's SMTP relay (Django's SMTP EmailBackend, using the
    EMAIL_HOST_USER/EMAIL_HOST_PASSWORD relay credentials in .env). Falls
    back to Brevo's HTTP Transactional API if the SMTP send raises, so a
    relay outage doesn't take email down entirely.
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
        print(f"Email sent to {to_email} via SMTP")
        return True, "sent via SMTP"
    except Exception as smtp_error:
        print(f"SMTP send failed for {to_email}: {smtp_error}")
        return _send_via_brevo_api(to_email, subject, html_content, plain_text, from_email)


def _send_via_brevo_api(to_email, subject, html_content, plain_text, from_email):
    """Fallback path for send_email_via_brevo: Brevo's HTTP Transactional API."""
    api_key = settings.BREVO_API_KEY

    if not api_key:
        print("BREVO_API_KEY not configured in .env")
        return False, "SMTP failed and BREVO_API_KEY not configured for fallback"

    url = "https://api.brevo.com/v3/smtp/email"

    payload = {
        "sender": {"email": from_email, "name": "TicketSwipe"},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_content,
        "textContent": plain_text,
    }

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "api-key": api_key,
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json()
        print(f"Email sent to {to_email} via Brevo API (SMTP fallback)")
        return True, result
    except requests.exceptions.RequestException as e:
        print(f"Brevo API fallback also failed for {to_email}: {str(e)}")
        if hasattr(e, 'response') and e.response:
            print(f"Response: {e.response.text}")
        return False, str(e)


def send_email_brevo(to_email, subject, html_template, context_data, from_email=None):
    """
    Wrapper for sending templated emails via Brevo API.
    """
    html_content = render_to_string(html_template, context_data)
    return send_email_via_brevo(to_email, subject, html_content, from_email)