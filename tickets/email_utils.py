"""
Reusable email utilities for the ICT Helpdesk Ticketing System.
"""
from django.core.mail import EmailMessage
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

DEFAULT_PASSWORD = 'DepEd123!'


def send_new_account_email(user_email, first_name, login_url):
    """
    Sends an HTML-formatted welcome email to a newly created employee account.
    Includes the default password and a link to the login page.
    """
    subject = 'ICT Helpdesk — Your New Account Has Been Created'

    html_body = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="margin:0; padding:0; background-color:#f4f6f9; font-family: 'Segoe UI', Arial, sans-serif;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:#f4f6f9; padding:40px 20px;">
            <tr>
                <td align="center">
                    <table role="presentation" width="560" cellspacing="0" cellpadding="0" style="background-color:#ffffff; border-radius:12px; overflow:hidden; box-shadow:0 2px 8px rgba(0,0,0,0.08);">
                        <!-- Header -->
                        <tr>
                            <td style="background: linear-gradient(135deg, #1e3a8a, #2563eb); padding:32px 40px; text-align:center;">
                                <h1 style="margin:0; color:#ffffff; font-size:22px; font-weight:700; letter-spacing:0.5px;">ICT Unit Helpdesk</h1>
                                <p style="margin:6px 0 0; color:#93c5fd; font-size:13px;">DepEd Division of Valenzuela</p>
                            </td>
                        </tr>
                        <!-- Body -->
                        <tr>
                            <td style="padding:36px 40px;">
                                <h2 style="margin:0 0 16px; color:#1e293b; font-size:18px; font-weight:700;">Welcome, {first_name}!</h2>
                                <p style="margin:0 0 20px; color:#475569; font-size:14px; line-height:1.7;">
                                    Your employee account for the ICT Helpdesk system has been successfully created.
                                    You can now log in to access the ticketing system and manage your assigned tasks.
                                </p>

                                <!-- Credentials Box -->
                                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 24px;">
                                    <tr>
                                        <td style="background-color:#eff6ff; border:1px solid #bfdbfe; border-radius:10px; padding:24px;">
                                            <p style="margin:0 0 4px; color:#64748b; font-size:11px; text-transform:uppercase; font-weight:700; letter-spacing:1px;">Your Login Credentials</p>
                                            <table role="presentation" cellspacing="0" cellpadding="0" style="margin-top:12px;">
                                                <tr>
                                                    <td style="color:#64748b; font-size:13px; padding:4px 16px 4px 0; font-weight:600;">Email:</td>
                                                    <td style="color:#1e293b; font-size:13px; font-weight:700;">{user_email}</td>
                                                </tr>
                                                <tr>
                                                    <td style="color:#64748b; font-size:13px; padding:4px 16px 4px 0; font-weight:600;">Password:</td>
                                                    <td style="color:#1e293b; font-size:13px; font-weight:700; font-family:monospace; letter-spacing:0.5px;">{DEFAULT_PASSWORD}</td>
                                                </tr>
                                            </table>
                                        </td>
                                    </tr>
                                </table>

                                <!-- Warning -->
                                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 28px;">
                                    <tr>
                                        <td style="background-color:#fef3c7; border:1px solid #fde68a; border-radius:8px; padding:14px 18px;">
                                            <p style="margin:0; color:#92400e; font-size:12px; line-height:1.6;">
                                                <strong>⚠️ Security Notice:</strong> For your protection, please change your password immediately after your first login. You will be prompted to do so when you access the system.
                                            </p>
                                        </td>
                                    </tr>
                                </table>

                                <!-- CTA Button -->
                                <table role="presentation" cellspacing="0" cellpadding="0" style="margin:0 auto;">
                                    <tr>
                                        <td align="center" style="border-radius:8px; background-color:#2563eb;">
                                            <a href="{login_url}" target="_blank" style="display:inline-block; padding:14px 36px; color:#ffffff; font-size:14px; font-weight:700; text-decoration:none; letter-spacing:0.3px;">
                                                Log In to Your Account →
                                            </a>
                                        </td>
                                    </tr>
                                </table>
                            </td>
                        </tr>
                        <!-- Footer -->
                        <tr>
                            <td style="background-color:#f8fafc; border-top:1px solid #e2e8f0; padding:20px 40px; text-align:center;">
                                <p style="margin:0; color:#94a3b8; font-size:11px; line-height:1.6;">
                                    This is an automated message from the ICT Helpdesk system.<br>
                                    &copy; 2026 DepEd Division of Valenzuela — ICT Unit. All rights reserved.
                                </p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """

    try:
        email = EmailMessage(
            subject=subject,
            body=html_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user_email],
        )
        email.content_subtype = 'html'
        email.send(fail_silently=False)
        logger.info(f"[Email] New account notification sent to {user_email}")
    except Exception as e:
        logger.error(f"[Email Error] Failed to send new account email to {user_email}: {e}")
        # Don't re-raise — the account is already created, email failure is non-blocking
