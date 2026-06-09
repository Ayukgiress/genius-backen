import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
import secrets
from datetime import datetime, timedelta, timezone
import httpx

from app.core.config import settings


def generate_verification_token() -> tuple[str, datetime]:
    """Generate a secure verification token that expires in 24 hours."""
    from datetime import timezone
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    return token, expires


def _send_email_sync(email: str, subject: str, html_content: str, text_content: str) -> bool:
    """Synchronous email sending function to be run in thread pool."""
    try:
        # Check if provider is valid and has a real API key (not a placeholder)
        if settings.EMAIL_PROVIDER == "resend" and settings.RESEND_API_KEY and "your_" not in settings.RESEND_API_KEY:
            return _send_via_resend(email, subject, html_content, text_content)
        elif settings.EMAIL_PROVIDER == "sendgrid" and settings.SENDGRID_API_KEY and "your_" not in settings.SENDGRID_API_KEY:
            return _send_via_sendgrid(email, subject, html_content, text_content)
        elif settings.EMAIL_PROVIDER == "brevo" and settings.BREVO_API_KEY and "your_" not in settings.BREVO_API_KEY:
            return _send_via_brevo(email, subject, html_content, text_content)
        else:
            # Default to SMTP if provider is "gmail" or if other providers are not properly configured
            return _send_via_smtp(email, subject, html_content, text_content)
    except Exception as e:
        print(f"Error in _send_email_sync: {e}")
        import traceback
        traceback.print_exc()
        return False


def _send_via_smtp(email: str, subject: str, html_content: str, text_content: str) -> bool:
    """Send email via SMTP (Gmail)."""
    import smtplib
    import ssl
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    try:
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        message["To"] = email

        part1 = MIMEText(text_content, "plain")
        part2 = MIMEText(html_content, "html")

        message.attach(part1)
        message.attach(part2)

        context = ssl.create_default_context()

        print(f"Attempting to connect to {settings.SMTP_HOST}:{settings.SMTP_PORT} (TLS: {settings.SMTP_TLS})")

        if settings.SMTP_PORT == 465:
            # Port 465 is for SMTP_SSL
            with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, context=context, timeout=settings.SMTP_TIMEOUT) as server:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.sendmail(settings.SMTP_FROM_EMAIL, email, message.as_string())
        else:
            # Port 587 is for STARTTLS
            try:
                with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=settings.SMTP_TIMEOUT) as server:
                    if settings.SMTP_TLS:
                        server.starttls(context=context)
                    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                    server.sendmail(settings.SMTP_FROM_EMAIL, email, message.as_string())
            except (OSError, smtplib.SMTPConnectError) as e:
                print(f"Failed to connect on port {settings.SMTP_PORT}: {e}")
                print(f"Attempting fallback to port 465 (SSL)...")
                # Fallback to 465 if 587 fails
                with smtplib.SMTP_SSL(settings.SMTP_HOST, 465, context=context, timeout=settings.SMTP_TIMEOUT) as server:
                    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                    server.sendmail(settings.SMTP_FROM_EMAIL, email, message.as_string())
                print(f"Email sent successfully to {email} using fallback port 465")
                return True

        print(f"Email sent successfully to {email}")
        return True
    except smtplib.SMTPAuthenticationError:
        print(f"SMTP Authentication Error: Please check your SMTP_USER and SMTP_PASSWORD.")
        return False
    except smtplib.SMTPConnectError:
        print(f"SMTP Connection Error: Could not connect to {settings.SMTP_HOST}:{settings.SMTP_PORT}.")
        return False
    except Exception as e:
        print(f"Error in SMTP email send: {e}")
        import traceback
        traceback.print_exc()
        return False


def _send_via_resend(email: str, subject: str, html_content: str, text_content: str) -> bool:
    """Send email via Resend API."""
    try:
        with httpx.Client() as client:
            response = client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "from": f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>",
                    "to": [email],
                    "subject": subject,
                    "html": html_content,
                    "text": text_content
                },
                timeout=10
            )
            if response.status_code == 200:
                print(f"Email sent successfully to {email} via Resend")
                return True
            else:
                print(f"Resend API error: {response.status_code} - {response.text}")
                return False
    except Exception as e:
        print(f"Error in Resend email send: {e}")
        return False


def _send_via_sendgrid(email: str, subject: str, html_content: str, text_content: str) -> bool:
    """Send email via SendGrid API."""
    try:
        with httpx.Client() as client:
            response = client.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={
                    "Authorization": f"Bearer {settings.SENDGRID_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "personalizations": [{
                        "to": [{"email": email}]
                    }],
                    "from": {"email": settings.SMTP_FROM_EMAIL, "name": settings.SMTP_FROM_NAME},
                    "subject": subject,
                    "content": [
                        {"type": "text/plain", "value": text_content},
                        {"type": "text/html", "value": html_content}
                    ]
                },
                timeout=10
            )
            if response.status_code == 202:
                print(f"Email sent successfully to {email} via SendGrid")
                return True
            else:
                print(f"SendGrid API error: {response.status_code} - {response.text}")
                return False
    except Exception as e:
        print(f"Error in SendGrid email send: {e}")
        return False


def _send_via_brevo(email: str, subject: str, html_content: str, text_content: str) -> bool:
    """Send email via Brevo API."""
    try:
        if not settings.BREVO_API_KEY:
            print("Brevo API key missing (BREVO_API_KEY not set)")
            return False

        # Be more explicit with timeouts for Render; avoid total request timeout hanging.
        timeout = httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0)

        payload = {
            "sender": {"email": settings.SMTP_FROM_EMAIL, "name": settings.SMTP_FROM_NAME},
            "to": [{"email": email}],
            "subject": subject,
            "htmlContent": html_content,
            "textContent": text_content,
        }

        # Simple retry for transient network timeouts
        last_exc: Exception | None = None
        for attempt in (1, 2):
            try:
                with httpx.Client(timeout=timeout) as client:
                    response = client.post(
                        "https://api.brevo.com/v3/smtp/email",
                        headers={
                            "api-key": settings.BREVO_API_KEY,
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )

                if response.status_code in (200, 201, 202):
                    print(f"Email sent successfully to {email} via Brevo (status={response.status_code})")
                    return True

                print(f"Brevo API error: {response.status_code} - {response.text}")
                return False
            except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout) as e:
                last_exc = e
                if attempt == 1:
                    # Small backoff then retry
                    import time
                    time.sleep(0.8)
                    continue
                break

        print(f"Error in Brevo email send: {last_exc}")
        return False

    except Exception as e:
        print(f"Error in Brevo email send: {e}")
        return False



async def send_verification_email(email: str, token: str) -> bool:
    """Send a verification email to the user."""
    import asyncio
    
    try:
        if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
            print(f"Email configuration missing!")
            print(f"SMTP_USER: {settings.SMTP_USER}")
            print(f"SMTP_PASSWORD: {'*' * len(settings.SMTP_PASSWORD) if settings.SMTP_PASSWORD else 'NOT SET'}")
            print(f"Verification token for {email}: {token}")
            print(f"Please configure SMTP credentials in .env file to enable email sending.")
            return False
        
        verification_url = f"{settings.FRONTEND_URL}/verify-email?token={token}"
        print(f"Verification URL for {email}: {verification_url}")
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2>Welcome to Genius API!</h2>
            <p>Thank you for registering. Please verify your email address by clicking the button below:</p>
            <p>
                <a href="{verification_url}" style="background-color: #4CAF50; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; display: inline-block;">
                    Verify Email
                </a>
            </p>
            <p>Or copy and paste this link into your browser:</p>
            <p>{verification_url}</p>
            <p>This link will expire in 24 hours.</p>
            <p>If you did not create an account, please ignore this email.</p>
            <hr>
            <p style="color: #666; font-size: 12px;">
                Best regards,<br>
                The Genius API Team
            </p>
        </body>
        </html>
        """
        
        text_content = f"""
        Welcome to Genius API!
        
        Thank you for registering. Please verify your email address by visiting this link:
        
        {verification_url}
        
        This link will expire in 24 hours.
        
        If you did not create an account, please ignore this email.
        
        Best regards,
        The Genius API Team
        """
        
        # Run synchronous SMTP in thread pool to avoid blocking
        result = await asyncio.to_thread(
            _send_email_sync, 
            email, 
            "Verify Your Email - Genius API", 
            html_content, 
            text_content
        )
        
        return result
    except Exception as e:
        print(f"Error sending verification email: {e}")
        import traceback
        traceback.print_exc()
        return False


async def send_password_reset_email(email: str, token: str) -> bool:
    """Send a password reset email to the user."""
    import asyncio
    
    try:
        if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
            print(f"Email configuration missing. Password reset token for {email}: {token}")
            return False
        
        reset_url = f"{settings.FRONTEND_URL}/reset-password?token={token}"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2>Reset Your Password</h2>
            <p>We received a request to reset your password. Click the button below to create a new password:</p>
            <p>
                <a href="{reset_url}" style="background-color: #f44336; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; display: inline-block;">
                    Reset Password
                </a>
            </p>
            <p>Or copy and paste this link into your browser:</p>
            <p>{reset_url}</p>
            <p>This link will expire in 1 hour.</p>
            <p>If you did not request a password reset, please ignore this email and your password will remain unchanged.</p>
            <hr>
            <p style="color: #666; font-size: 12px;">
                Best regards,<br>
                The Genius API Team
            </p>
        </body>
        </html>
        """
        
        text_content = f"""
        Reset Your Password
        
        We received a request to reset your password. Visit this link to create a new password:
        
        {reset_url}
        
        This link will expire in 1 hour.
        
        If you did not request a password reset, please ignore this email.
        
        Best regards,
        The Genius API Team
        """
        
        # Run synchronous SMTP in thread pool to avoid blocking
        result = await asyncio.to_thread(
            _send_email_sync, 
            email, 
            "Reset Your Password - Genius API", 
            html_content, 
            text_content
        )
        
        return result
    except Exception as e:
        print(f"Error sending password reset email: {e}")
        import traceback
        traceback.print_exc()
        return False
