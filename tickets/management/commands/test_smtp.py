"""
Management command to test Gmail / SMTP configuration and send a test OTP email.
Usage:
    python manage.py test_smtp recipient@gmail.com
"""
import sys
import traceback
from django.core.management.base import BaseCommand
from django.conf import settings
from tickets.email_utils import send_otp_email
from tickets.models import PasswordResetOTP


class Command(BaseCommand):
    help = 'Tests SMTP configuration by sending a branded test OTP email to the specified address.'

    def add_arguments(self, parser):
        parser.add_argument(
            'recipient_email',
            type=str,
            help='The recipient email address to receive the test OTP email.',
        )
        parser.add_argument(
            '--name',
            type=str,
            default='Test Recipient',
            help='Recipient display name (default: "Test Recipient").',
        )

    def handle(self, *args, **options):
        recipient = options['recipient_email'].strip()
        recipient_name = options['name']
        test_code = PasswordResetOTP.generate_code()

        self.stdout.write(self.style.MIGRATE_HEADING("=" * 60))
        self.stdout.write(self.style.MIGRATE_HEADING("  ICT Helpdesk — SMTP Configuration Diagnostic Tool"))
        self.stdout.write(self.style.MIGRATE_HEADING("=" * 60))

        # 1. Print Active Email Settings
        backend = getattr(settings, 'EMAIL_BACKEND', 'Not set')
        host = getattr(settings, 'EMAIL_HOST', 'Not set')
        port = getattr(settings, 'EMAIL_PORT', 'Not set')
        use_tls = getattr(settings, 'EMAIL_USE_TLS', False)
        use_ssl = getattr(settings, 'EMAIL_USE_SSL', False)
        timeout = getattr(settings, 'EMAIL_TIMEOUT', 10)
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'Not set')
        user = getattr(settings, 'EMAIL_HOST_USER', '')
        password = getattr(settings, 'EMAIL_HOST_PASSWORD', '')

        # Mask user & password for safe terminal output
        if user and '@' in user:
            user_parts = user.split('@')
            masked_user = f"{user_parts[0][:2]}***@{user_parts[1]}"
        elif user:
            masked_user = f"{user[:2]}***"
        else:
            masked_user = "(empty)"

        pwd_status = f"Configured ({len(password)} characters)" if password else "(empty - not configured)"

        self.stdout.write(f"  * EMAIL_BACKEND      : {backend}")
        self.stdout.write(f"  * EMAIL_HOST         : {host}")
        self.stdout.write(f"  * EMAIL_PORT         : {port}")
        self.stdout.write(f"  * EMAIL_USE_TLS      : {use_tls}")
        self.stdout.write(f"  * EMAIL_USE_SSL      : {use_ssl}")
        self.stdout.write(f"  * EMAIL_TIMEOUT      : {timeout}s")
        self.stdout.write(f"  * EMAIL_HOST_USER    : {masked_user}")
        self.stdout.write(f"  * EMAIL_HOST_PASSWORD: {pwd_status}")
        self.stdout.write(f"  * DEFAULT_FROM_EMAIL : {from_email}")
        self.stdout.write("-" * 60)

        # Warning checks
        if not user or not password:
            self.stdout.write(self.style.WARNING(
                "  [WARNING] EMAIL_HOST_USER or EMAIL_HOST_PASSWORD is empty in .env.\n"
                "  If using live SMTP, delivery will likely fail with authentication errors."
            ))

        self.stdout.write(f"\nAttempting to send test OTP email to: {recipient}...")
        self.stdout.write(f"Generated test OTP code: {test_code}\n")

        # 2. Attempt Send
        try:
            success, error_msg = send_otp_email(
                recipient_email=recipient,
                code=test_code,
                recipient_name=recipient_name,
            )

            # Check if this was a simulated fallback
            unconfigured_passwords = {'', 'your-brevo-smtp-key', 'your-actual-app-password', 'your-16-char-app-password'}
            is_simulated = getattr(settings, 'DEBUG', False) and password in unconfigured_passwords

            if success and is_simulated:
                self.stdout.write(self.style.WARNING(
                    f"\n[SIMULATED DEV DELIVERY] OTP was printed to console only.\n"
                    f"-> No actual email was sent to {recipient} over the internet because\n"
                    f"   EMAIL_HOST_PASSWORD in .env is still set to '{password or '(empty)'}'.\n\n"
                    f"To deliver REAL emails to your Gmail inbox:\n"
                    f"1. Sign up at https://www.brevo.com (100% free, no credit card)\n"
                    f"2. Go to 'SMTP & API' -> 'SMTP' -> 'Generate a new SMTP key'\n"
                    f"3. Paste your login email in EMAIL_HOST_USER and the key in EMAIL_HOST_PASSWORD in .env\n"
                    f"4. Run this command again to send a live email!"
                ))
            elif success:
                self.stdout.write(self.style.SUCCESS(
                    f"\n[SUCCESS] REAL email sent via {host}:{port} to {recipient}!\n"
                    f"Please check your inbox (and spam/junk folder)."
                ))
            else:
                self.stdout.write(self.style.ERROR(
                    f"\n[FAILURE] Failed to send email:\n  {error_msg}\n"
                ))
                self._print_troubleshooting_tips(error_msg, host, user)

        except Exception as exc:
            self.stdout.write(self.style.ERROR(
                f"\n[EXCEPTION] Unexpected error during SMTP transmission:\n"
            ))
            traceback.print_exc(file=sys.stdout)
            self._print_troubleshooting_tips(str(exc), host, user)

        self.stdout.write(self.style.MIGRATE_HEADING("=" * 60))

    def _print_troubleshooting_tips(self, error_msg, host, user):
        self.stdout.write(self.style.WARNING("\nTroubleshooting Tips:"))
        err_lower = str(error_msg).lower()
        if 'authentication' in err_lower or '535' in err_lower or 'badcredentials' in err_lower or 'unauthorized' in err_lower:
            self.stdout.write(
                "  1. If using Brevo (smtp-relay.brevo.com):\n"
                "     - Sign up for a free account at: https://www.brevo.com\n"
                "     - Go to: 'SMTP & API' -> 'SMTP' tab -> Click 'Generate a new SMTP key'\n"
                "     - Set EMAIL_HOST_USER=<your-brevo-login-email> in .env\n"
                "     - Set EMAIL_HOST_PASSWORD=<your-brevo-smtp-key> in .env\n"
                "  2. If using Gmail (smtp.gmail.com):\n"
                "     - Google requires an App Password (16 characters) generated under 2-Step Verification.\n"
                "  3. Verify that your login email and SMTP key have no extra spaces or typographical errors."
            )
        elif 'connection refused' in err_lower or 'timeout' in err_lower or 'timed out' in err_lower or '10060' in err_lower:
            self.stdout.write(
                "  1. Port 587 or the SMTP host might be blocked by your local network / firewall / ISP.\n"
                "  2. Verify your internet connection.\n"
                "  3. You can test SSL port 465 with EMAIL_PORT=465, EMAIL_USE_TLS=False, EMAIL_USE_SSL=True."
            )
        else:
            self.stdout.write(
                "  - Check your .env configuration.\n"
                "  - In local development, if EMAIL_HOST_PASSWORD is left unconfigured, the system automatically\n"
                "    prints the OTP code directly to your terminal so you are never blocked during testing."
            )

