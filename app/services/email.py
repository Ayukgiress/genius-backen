import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
import secrets
from datetime import datetime, timedelta, timezone

from app.core.config import settings


def generate_verification_token() -> tuple[str, datetime]:
    """Generate a secure verification token that expires in 24 hours."""
    from datetime import timezone
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    return token, expires


def _send_email_sync(email: str, subject: str, html_content: str, text_content: str) -> bool:
    """Synchronous email sending function to be run in thread pool."""
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
        
        print(f"Attempting to login to {settings.SMTP_HOST}:{settings.SMTP_PORT} as {settings.SMTP_USER}")
        
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.starttls(context=context)
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_FROM_EMAIL, email, message.as_string())
        
        print(f"Email sent successfully to {email}")
        return True
    except Exception as e:
        print(f"Error in _send_email_sync: {e}")
        import traceback
        traceback.print_exc()
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
