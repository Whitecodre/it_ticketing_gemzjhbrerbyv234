from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify
from django.contrib.auth import get_user_model
from apps.knowledge_base.models import Article
from apps.knowledge_base.sanitize import sanitize_html
from apps.common.models import Category

User = get_user_model()


def _img(picsum_id, alt, caption=None):
    """A full-width article image via Lorem Picsum's stable per-ID endpoint
    (deterministic, hotlink-friendly, no API key) — not a real screenshot,
    but a real loaded <img> so KB testing can actually exercise image
    rendering/layout instead of staring at a blank content area."""
    fig = (
        f'<p><img src="https://picsum.photos/id/{picsum_id}/900/420" '
        f'alt="{alt}" width="900" height="420"></p>'
    )
    if caption:
        fig += f'<p style="text-align: center"><em>{caption}</em></p>'
    return fig


class Command(BaseCommand):
    help = 'Seed well-formed knowledge base articles (headings, lists, callouts, images) for KB testing'

    def handle(self, *args, **options):
        categories = {}
        cat_names = ['IT', 'HR', 'Operations', 'General', 'Security']
        for name in cat_names:
            cat, _ = Category.objects.get_or_create(
                name=name,
                defaults={'slug': slugify(name)}
            )
            categories[name] = cat
            self.stdout.write(f'✅ Category: {name}')

        author = (
            User.objects.filter(role='AGENT', is_active=True).first()
            or User.objects.filter(is_superuser=True).first()
        )
        if not author:
            self.stdout.write(self.style.ERROR('No agent or superuser found. Please create one first.'))
            return

        articles_data = [
            {
                'title': 'Resetting your password and multi-factor authentication',
                'category': 'IT',
                'visibility': 'PUBLIC',
                'status': 'PUBLISHED',
                'content': ''.join([
                    '<p>If you’re locked out of your account or your authenticator app is showing the wrong '
                    'codes, you don’t need to wait for IT to reset things by hand — the self-service portal '
                    'covers both cases in under five minutes.</p>',

                    _img(0, 'Laptop showing a login screen', 'The self-service reset portal, reachable from any device'),

                    '<h2>Resetting a forgotten password</h2>',
                    '<ol>'
                    '<li>Go to the login page and select <strong>Forgot password</strong>.</li>'
                    '<li>Enter the email address linked to your account.</li>'
                    '<li>Check your inbox for a reset link — it expires after 30 minutes.</li>'
                    '<li>Choose a new password of at least 12 characters, mixing letters, numbers, and a symbol.</li>'
                    '</ol>',

                    '<div class="kb-callout"><p><strong>Note:</strong> If the reset email doesn’t arrive within '
                    'a few minutes, check your spam folder before raising a ticket — it’s the most common '
                    'cause of a "missing" reset email.</p></div>',

                    '<h2>Resetting multi-factor authentication (MFA)</h2>',
                    '<p>MFA can’t be self-reset the same way, since that would defeat the point of having it. '
                    'If you’ve lost your device or your authenticator app stopped generating valid codes:</p>',
                    '<ol>'
                    '<li>Raise an Incident ticket with category <strong>Account Access</strong>.</li>'
                    '<li>Be ready to verify your identity — your manager’s name and your employee ID are usually enough.</li>'
                    '<li>An agent will issue a temporary bypass code and walk you through re-enrolling a device.</li>'
                    '</ol>',

                    '<div class="kb-callout"><p><strong>Security note:</strong> IT will never ask for your password '
                    'or a live MFA code over chat, email, or phone. If someone claiming to be IT asks for either, '
                    'end the conversation and report it — see “Reporting a suspected phishing or security '
                    'incident” below.</p></div>',
                ]),
            },
            {
                'title': 'Connecting to the VPN for remote and offshore work',
                'category': 'IT',
                'visibility': 'PUBLIC',
                'status': 'PUBLISHED',
                'content': ''.join([
                    '<p>The corporate VPN is required for accessing internal systems (file shares, internal '
                    'dashboards, the reporting server) from outside the office network — including from a vessel '
                    'or site with satellite internet, where the extra encryption overhead is worth planning for.</p>',

                    _img(1015, 'Person working on a laptop near a window with a view of water', 'VPN access works the same whether you’re on land or offshore — connection quality is the only variable'),

                    '<h2>First-time setup</h2>',
                    '<ol>'
                    '<li>Install the VPN client from the Software Center (Windows) or Self Service (Mac).</li>'
                    '<li>Launch it and sign in with your usual company email and password.</li>'
                    '<li>Approve the MFA prompt sent to your phone.</li>'
                    '<li>Select the <strong>nearest</strong> gateway region — this matters more than it sounds; '
                    'the wrong region can add 200–400ms of latency.</li>'
                    '</ol>',

                    '<h2>Connecting over satellite or low-bandwidth links</h2>',
                    '<p>If you’re connecting from a vessel or a remote site on satellite internet, a couple of '
                    'settings make a real difference:</p>',
                    '<ul>'
                    '<li>Enable <strong>Low Bandwidth Mode</strong> in the client’s Advanced settings — it '
                    'reduces keep-alive traffic that otherwise competes with real work over a slow link.</li>'
                    '<li>Avoid large file transfers over VPN during working hours if the vessel is sharing '
                    'bandwidth with navigation/comms systems — schedule big syncs for off-peak hours instead.</li>'
                    '<li>If the connection keeps dropping every few minutes, that’s almost always the satellite '
                    'link itself re-negotiating, not the VPN — the client will auto-reconnect on its own.</li>'
                    '</ul>',

                    '<div class="kb-callout"><p><strong>Tip:</strong> Keep the VPN client’s connection log open '
                    '(View → Show Log) before calling in a connectivity issue — it tells the agent in seconds '
                    'whether the problem is authentication, the gateway, or the link itself.</p></div>',

                    '<h2>Common errors</h2>',
                    '<table><thead><tr><th>Error</th><th>Likely cause</th><th>What to try</th></tr></thead><tbody>'
                    '<tr><td>Error 809</td><td>Firewall/NAT blocking the VPN port</td><td>Switch to the TCP-443 fallback profile</td></tr>'
                    '<tr><td>Error 691</td><td>Wrong password or expired account</td><td>Reset your password, then retry</td></tr>'
                    '<tr><td>Connects, then drops after ~1 minute</td><td>MFA session timeout</td><td>Re-approve the MFA prompt promptly next time</td></tr>'
                    '</tbody></table>',
                ]),
            },
            {
                'title': 'Requesting new hardware or a software license',
                'category': 'Operations',
                'visibility': 'PUBLIC',
                'status': 'PUBLISHED',
                'content': ''.join([
                    '<p>Hardware and license requests go through the Service Request form, not a general ticket — '
                    'this routes them straight to fulfillment instead of an agent’s general queue, and keeps '
                    'stock and licensing counts accurate.</p>',

                    _img(180, 'Laptop and accessories laid out on a desk', 'New-starter kits are prepared from stock before the request is marked fulfilled'),

                    '<h2>Submitting the request</h2>',
                    '<ol>'
                    '<li>Open <strong>New Request → Service Request</strong>.</li>'
                    '<li>Choose the <strong>Hardware Support</strong> category (or <strong>Software License</strong> '
                    'for licenses).</li>'
                    '<li>Fill in the quantity and asset type — be specific (e.g. "Laptop" vs "Docking Station") '
                    'so fulfillment can check real stock instead of guessing.</li>'
                    '<li>If this is for a new starter, attach their start date in the request details so it can be '
                    'prioritized correctly.</li>'
                    '</ol>',

                    '<h2>What happens next</h2>',
                    '<p>Every service request goes through review before it reaches fulfillment:</p>',
                    '<ul>'
                    '<li>Your department lead reviews it first.</li>'
                    '<li>The IT lead reviews it second (skipped only if you’re already in the IT department).</li>'
                    '<li>Once approved, it moves to the fulfillment queue, where stock is checked or a purchase is '
                    'raised if nothing’s in stock.</li>'
                    '<li>You’ll get a notification to confirm receipt once the item is ready — the ticket '
                    'isn’t closed until you confirm.</li>'
                    '</ul>',

                    '<div class="kb-callout"><p><strong>Note:</strong> If something’s wrong when it arrives '
                    '(wrong item, missing accessory), use the <strong>Not received</strong> option on the '
                    'confirmation card rather than opening a new ticket — it reopens the same request with the '
                    'fulfillment context already attached.</p></div>',
                ]),
            },
            {
                'title': 'Printer troubleshooting: offline, stuck jobs, and paper jams',
                'category': 'IT',
                'visibility': 'PUBLIC',
                'status': 'PUBLISHED',
                'content': ''.join([
                    '<p>Most printer issues clear up with one of the three fixes below — worth trying before '
                    'raising a ticket, since it’ll save you the wait.</p>',

                    _img(96, 'Office printer', 'Shared office printers are the most common source of print-queue tickets'),

                    '<h2>Printer shows as offline</h2>',
                    '<ol>'
                    '<li>Confirm the printer’s display panel shows it’s actually powered on and idle, not '
                    'mid-error.</li>'
                    '<li>On your PC, open <strong>Settings → Printers</strong> and remove, then re-add, the '
                    'printer — this clears a stale network handle more often than you’d expect.</li>'
                    '<li>Still offline after that? Restart the Print Spooler service '
                    '(<code>services.msc</code> → Print Spooler → Restart).</li>'
                    '</ol>',

                    '<h2>A print job is stuck in the queue</h2>',
                    '<p>A stuck job blocks everyone else’s printing behind it, so clear it rather than waiting:</p>',
                    '<ol>'
                    '<li>Open the print queue and cancel the stuck job specifically — don’t just resend it, '
                    'that usually queues a second stuck copy.</li>'
                    '<li>If cancelling doesn’t remove it, restart the Print Spooler service (same as above) — '
                    'this force-clears the queue.</li>'
                    '</ol>',

                    '<div class="kb-callout"><p><strong>Warning:</strong> Restarting the Print Spooler cancels '
                    '<em>everyone’s</em> pending jobs on that printer, not just yours — give people a heads-up '
                    'in the department chat first if the printer is shared and busy.</p></div>',

                    '<h2>Paper jams</h2>',
                    '<p>Always follow the direction arrows printed inside the access panel when clearing a jam — '
                    'pulling paper backward against the rollers is the single most common cause of a jam that '
                    'needs an actual technician visit instead of a two-minute fix.</p>',
                ]),
            },
            {
                'title': 'Setting up company email on your phone',
                'category': 'IT',
                'visibility': 'PUBLIC',
                'status': 'PUBLISHED',
                'content': ''.join([
                    '<p>Company email is supported on both iOS and Android through the standard mail app — no '
                    'separate corporate app required.</p>',

                    _img(160, 'Person checking a phone', 'Mail sync typically completes within a minute of adding the account'),

                    '<h2>iOS</h2>',
                    '<ol>'
                    '<li>Go to <strong>Settings → Mail → Accounts → Add Account → Exchange</strong>.</li>'
                    '<li>Enter your company email address and password.</li>'
                    '<li>Approve the MFA prompt when it appears.</li>'
                    '<li>Leave Mail, Contacts, and Calendars all switched on unless you specifically don’t want '
                    'one syncing.</li>'
                    '</ol>',

                    '<h2>Android</h2>',
                    '<ol>'
                    '<li>Open the Gmail app → tap your profile picture → <strong>Add another account</strong>.</li>'
                    '<li>Choose <strong>Exchange and Office 365</strong>.</li>'
                    '<li>Enter your company email address and password, then approve the MFA prompt.</li>'
                    '</ol>',

                    '<div class="kb-callout"><p><strong>Note:</strong> Company policy requires a device passcode or '
                    'biometric lock before mail will sync — if setup fails at the last step with no clear error, '
                    'this is almost always why.</p></div>',

                    '<h2>Mail isn’t syncing after setup</h2>',
                    '<ul>'
                    '<li>Remove the account and re-add it — fixes the majority of sync failures.</li>'
                    '<li>Confirm the device is on a supported OS version; very old OS versions get blocked by '
                    'the mail server’s security policy.</li>'
                    '<li>Still stuck? Raise an Incident with category <strong>Email</strong> and mention your device '
                    'model and OS version — it’s the first thing an agent will ask for anyway.</li>'
                    '</ul>',
                ]),
            },
            {
                'title': 'Reporting a suspected phishing or security incident',
                'category': 'Security',
                'visibility': 'PUBLIC',
                'status': 'PUBLISHED',
                'content': ''.join([
                    '<p>Speed matters more than certainty here — report anything that looks even slightly off '
                    'rather than spending time investigating it yourself first.</p>',

                    _img(48, 'Person typing on a laptop keyboard', 'A minute spent reporting a suspicious email is cheaper than the alternative'),

                    '<div class="kb-callout"><p><strong>Warning:</strong> Do not click links or open attachments in '
                    'a message you suspect is phishing, even "just to check" — forward or report it instead.</p></div>',

                    '<h2>If you received a suspicious email</h2>',
                    '<ol>'
                    '<li>Don’t click any links or open attachments.</li>'
                    '<li>Use your mail client’s <strong>Report Phishing</strong> button if it has one — this '
                    'also feeds our spam filter automatically.</li>'
                    '<li>If there’s no built-in report option, raise an Incident ticket with category '
                    '<strong>Security</strong> and attach the email as a file (not forwarded inline, which can '
                    'strip the headers we need).</li>'
                    '</ol>',

                    '<h2>If you think you already clicked something you shouldn’t have</h2>',
                    '<ol>'
                    '<li>Disconnect the device from Wi-Fi/network immediately — don’t shut it down, a live '
                    'connection often helps investigation more than a clean shutdown does.</li>'
                    '<li>Raise a <strong>P1 Incident</strong> under Security right away and say plainly what happened.</li>'
                    '<li>Change your password from a <em>different</em>, trusted device once you’ve reported it.</li>'
                    '</ol>',

                    '<p>You will not be in trouble for reporting a mistake — the only bad outcome here is not '
                    'reporting it and giving an incident more time to spread.</p>',
                ]),
            },
        ]

        created_count = 0
        for data in articles_data:
            # Article.slug is a plain SlugField (max_length defaults to 50) —
            # several of these titles are longer than that once slugified.
            slug = slugify(data['title'])[:50]
            content = sanitize_html(data['content'])
            defaults = {
                'title': data['title'],
                'category': categories.get(data['category']),
                'author': author,
                'content': content,
                'visibility': data['visibility'],
                'status': data['status'],
            }
            if data['status'] == 'PUBLISHED':
                defaults['published_at'] = timezone.now()
                defaults['published_by'] = author

            article, created = Article.objects.get_or_create(slug=slug, defaults=defaults)
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f'✅ Created article: {article.title}'))
            else:
                self.stdout.write(f'ℹ️ Article already exists: {article.title}')

        self.stdout.write(self.style.SUCCESS(f'\n🎉 Done! {created_count} new articles created.'))
