import os
import json
import logging
from config.settings import FRONTEND_URL

logger = logging.getLogger(__name__)


def _sanitize_header(value: str) -> str:
    """Strip CR/LF characters that could inject additional SMTP headers."""
    if not value:
        return ""
    return value.replace("\r", "").replace("\n", "").replace("\0", "")


def send_verification_email(email: str, code: str) -> bool:
    provider  = os.getenv("EMAIL_PROVIDER", "").lower()
    from_addr = os.getenv("EMAIL_FROM", "noreply@acordly.ai")
    subject   = "Your Verification Code"
    body_txt  = f"Your verification code is: {code}\n\nExpires in 10 minutes."
    body_html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:24px;">
      <h2 style="color:#1e293b;">Verify your account</h2>
      <p style="color:#475569;">Enter the code below to complete sign-up.</p>
      <div style="background:#f1f5f9;border-radius:8px;padding:24px;text-align:center;margin-bottom:24px;">
        <span style="font-size:36px;font-weight:700;letter-spacing:8px;color:#0f172a;">{code}</span>
      </div>
      <p style="color:#64748b;font-size:13px;">Expires in <strong>10 minutes</strong>.</p>
    </div>
    """
    return _send_generic_email(email, subject, body_txt, body_html, provider, from_addr)


def send_arq_email(
    to_email: str,
    client_name: str,
    producer_full_name: str,
    producer_first_name: str,
    arq_link: str,
) -> bool:
    """Send ARQ questionnaire invitation email to client."""
    subject   = f"Insurance Information Request from {producer_first_name}"
    greeting  = f"Hi {client_name}," if client_name and client_name.strip() else "Hello,"
    body_txt  = (
        f"{greeting}\n\n"
        f"{producer_full_name} needs your help with a few details to complete your commercial insurance application.\n\n"
        f"Please click the link below to answer some simple questions. This will only take a couple of minutes.\n\n"
        f"{arq_link}\n\n"
        f"This link will expire in 7 days.\n\n"
        f"Thank you,\nThe Insurance Team"
    )
    body_html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
    <body style="margin:0;padding:0;background:#f8fafc;font-family:Arial,sans-serif;">
      <div style="max-width:560px;margin:40px auto;background:#fff;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,0.08);overflow:hidden;">
        <div style="background:linear-gradient(135deg,#0f172a 0%,#1e293b 100%);padding:28px 32px;">
          <p style="color:#e6007a;font-size:22px;font-weight:700;margin:0;letter-spacing:-0.5px;">Primble</p>
          <p style="color:#94a3b8;font-size:12px;margin:4px 0 0 0;">Commercial Insurance Platform</p>
        </div>
        <div style="padding:32px;">
          <p style="font-size:16px;color:#1e293b;font-weight:600;margin:0 0 12px 0;">{greeting}</p>
          <p style="font-size:15px;color:#475569;line-height:1.6;margin:0 0 24px 0;">
            <strong style="color:#1e293b;">{producer_full_name}</strong> needs your help with a few details to complete your commercial insurance application.
            Please click the button below to answer some simple questions. This will only take a couple of minutes.
          </p>
          <div style="text-align:center;margin:32px 0;">
            <a href="{arq_link}"
               style="background:#e6007a;color:#fff;text-decoration:none;padding:14px 36px;border-radius:8px;font-size:16px;font-weight:600;display:inline-block;letter-spacing:0.3px;">
              Answer Questions
            </a>
          </div>
          <p style="font-size:12px;color:#94a3b8;text-align:center;margin:0 0 8px 0;">
            Or copy this link: <a href="{arq_link}" style="color:#e6007a;">{arq_link}</a>
          </p>
          <p style="font-size:11px;color:#cbd5e1;text-align:center;margin:0;">This link expires in 7 days.</p>
        </div>
        <div style="background:#f8fafc;padding:16px 32px;border-top:1px solid #e2e8f0;text-align:center;">
          <p style="font-size:11px;color:#94a3b8;margin:0;">
            Powered by <a href="{FRONTEND_URL}" style="color:#e6007a;font-weight:600;text-decoration:none;">Primble</a>
          </p>
        </div>
      </div>
    </body>
    </html>
    """
    return _send_generic_email(to_email, subject, body_txt, body_html)


def send_arq_reminder_email(
    to_email: str,
    client_name: str,
    producer_full_name: str,
    producer_first_name: str,
    arq_link: str,
) -> bool:
    """Send ARQ reminder email to client."""
    subject   = f"Reminder: Insurance Information Request from {producer_first_name}"
    greeting  = f"Hi {client_name}," if client_name and client_name.strip() else "Hello,"
    body_txt  = (
        f"{greeting}\n\n"
        f"This is a friendly reminder that {producer_full_name} is still waiting for your response "
        f"to complete your commercial insurance application.\n\n"
        f"Please click the link below to answer a few simple questions.\n\n"
        f"{arq_link}\n\n"
        f"Thank you,\nThe Insurance Team"
    )
    body_html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
    <body style="margin:0;padding:0;background:#f8fafc;font-family:Arial,sans-serif;">
      <div style="max-width:560px;margin:40px auto;background:#fff;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,0.08);overflow:hidden;">
        <div style="background:linear-gradient(135deg,#0f172a 0%,#1e293b 100%);padding:28px 32px;">
          <p style="color:#e6007a;font-size:22px;font-weight:700;margin:0;">Primble</p>
          <p style="color:#94a3b8;font-size:12px;margin:4px 0 0 0;">Commercial Insurance Platform</p>
        </div>
        <div style="padding:32px;">
          <div style="background:#fef9c3;border:1px solid #fde047;border-radius:8px;padding:12px 16px;margin-bottom:20px;">
            <p style="font-size:13px;color:#854d0e;margin:0;font-weight:600;">⏰ Friendly Reminder</p>
          </div>
          <p style="font-size:16px;color:#1e293b;font-weight:600;margin:0 0 12px 0;">{greeting}</p>
          <p style="font-size:15px;color:#475569;line-height:1.6;margin:0 0 24px 0;">
            <strong style="color:#1e293b;">{producer_full_name}</strong> is still waiting for your response
            to complete your commercial insurance application. It only takes a couple of minutes.
          </p>
          <div style="text-align:center;margin:32px 0;">
            <a href="{arq_link}"
               style="background:#e6007a;color:#fff;text-decoration:none;padding:14px 36px;border-radius:8px;font-size:16px;font-weight:600;display:inline-block;">
              Complete Questionnaire
            </a>
          </div>
          <p style="font-size:12px;color:#94a3b8;text-align:center;margin:0;">
            <a href="{arq_link}" style="color:#e6007a;">{arq_link}</a>
          </p>
        </div>
        <div style="background:#f8fafc;padding:16px 32px;border-top:1px solid #e2e8f0;text-align:center;">
          <p style="font-size:11px;color:#94a3b8;margin:0;">
            Powered by <a href="{FRONTEND_URL}" style="color:#e6007a;font-weight:600;text-decoration:none;">Primble</a>
          </p>
        </div>
      </div>
    </body>
    </html>
    """
    return _send_generic_email(to_email, subject, body_txt, body_html)


# PATCH for backend/services/email_service.py
# Replace send_arq_submitted_notification with this version that includes a session link

def send_arq_submitted_notification(
    producer_email: str,
    producer_name: str,
    client_name: str,
    client_email: str,
    fields_filled: int,
    session_id: str = "",          # ADD THIS PARAM
    frontend_url: str = "",        # ADD THIS PARAM
) -> bool:
    """Notify producer that client has submitted the ARQ — includes link back to session."""
    import os
    if not frontend_url:
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")

    # Deep link: frontend reads ?resume_session=<id> on load to reopen editor
    session_link = f"{frontend_url}?resume_session={session_id}" if session_id else frontend_url

    subject   = f"Client Submitted Insurance Questionnaire — {client_name or client_email}"
    body_txt  = (
        f"Hi {producer_name or 'there'},\n\n"
        f"{client_name or client_email} has submitted answers to your insurance questionnaire.\n\n"
        f"{fields_filled} field(s) have been updated in your ACORD forms.\n\n"
        f"Click the link below to review and continue editing:\n{session_link}\n\n"
        f"The Primble Team"
    )
    body_html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="margin:0;padding:0;background:#f8fafc;font-family:Arial,sans-serif;">
      <div style="max-width:520px;margin:40px auto;background:#fff;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,0.08);overflow:hidden;">
        <div style="background:linear-gradient(135deg,#0f172a 0%,#1e293b 100%);padding:24px 28px;">
          <p style="color:#e6007a;font-size:20px;font-weight:700;margin:0;">Primble</p>
        </div>
        <div style="padding:28px;">
          <div style="background:#dcfce7;border:1px solid #86efac;border-radius:8px;padding:14px 16px;margin-bottom:20px;">
            <p style="font-size:14px;color:#166534;margin:0;font-weight:600;">✅ Client Response Received</p>
          </div>
          <p style="font-size:15px;color:#475569;line-height:1.6;margin:0 0 16px 0;">
            Hi <strong>{producer_name or "there"}</strong>,
          </p>
          <p style="font-size:15px;color:#475569;line-height:1.6;margin:0 0 16px 0;">
            <strong style="color:#1e293b;">{client_name or client_email}</strong> has submitted answers to your insurance questionnaire.
            <strong>{fields_filled}</strong> field(s) have been automatically updated in your ACORD forms.
          </p>
          <div style="text-align:center;margin:24px 0;">
            <a href="{session_link}"
               style="background:#e6007a;color:#fff;text-decoration:none;padding:12px 32px;border-radius:8px;font-size:15px;font-weight:600;display:inline-block;">
              Open Session &amp; Review Changes
            </a>
          </div>
          <p style="font-size:12px;color:#94a3b8;text-align:center;margin:0;">
            Or copy this link: <a href="{session_link}" style="color:#e6007a;">{session_link}</a>
          </p>
        </div>
        <div style="background:#f8fafc;padding:14px 28px;border-top:1px solid #e2e8f0;text-align:center;">
          <p style="font-size:11px;color:#94a3b8;margin:0;">
            Powered by <a href="{frontend_url}" style="color:#e6007a;font-weight:600;text-decoration:none;">Primble</a>
          </p>
        </div>
      </div>
    </body>
    </html>
    """
    return _send_generic_email(producer_email, subject, body_txt, body_html)


def _send_generic_email(
    to_email: str,
    subject: str,
    body_txt: str,
    body_html: str,
    provider: str = None,
    from_addr: str = None,
) -> bool:
    if provider is None:
        provider = os.getenv("EMAIL_PROVIDER", "").lower()
    if from_addr is None:
        from_addr = os.getenv("EMAIL_FROM", "noreply@acordly.ai")

    logger.info(f"Sending email provider={provider!r} to={to_email} subject={subject!r}")

    if provider == "resend":
        api_key = os.getenv("RESEND_API_KEY", "")
        if not api_key:
            logger.error("RESEND_API_KEY is not set — email not sent")
            return False

        def _do_resend():
            import urllib.request, urllib.error
            payload = json.dumps({
                "from": from_addr, "to": [to_email],
                "subject": subject, "html": body_html, "text": body_txt,
            }).encode()
            req = urllib.request.Request(
                "https://api.resend.com/emails", data=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "acordly-backend/1.0",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.status
            except urllib.error.HTTPError as he:
                body = ""
                try:
                    body = he.read().decode("utf-8", errors="replace")[:500]
                except Exception:
                    pass
                raise ValueError(f"Resend HTTP {he.code} from={from_addr}: {body}") from he

        try:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(_do_resend).result(timeout=15)
            logger.info(f"Resend: email sent to {to_email} from={from_addr}")
            return True
        except Exception as ex:
            logger.error(f"Resend email FAILED to={to_email} from={from_addr}: {ex}")
            return False

    elif provider == "sendgrid":
        api_key = os.getenv("SENDGRID_API_KEY", "")
        if not api_key:
            logger.error("SENDGRID_API_KEY is not set — email not sent")
            return False

        def _do_sendgrid():
            import urllib.request
            payload = json.dumps({
                "personalizations": [{"to": [{"email": to_email}]}],
                "from": {"email": from_addr},
                "subject": subject,
                "content": [{"type": "text/plain", "value": body_txt}, {"type": "text/html", "value": body_html}],
            }).encode()
            req = urllib.request.Request(
                "https://api.sendgrid.com/v3/mail/send", data=payload,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=10):
                pass
            return True

        try:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(_do_sendgrid).result(timeout=20)
            logger.info(f"SendGrid: email sent to {to_email}")
            return result
        except Exception as ex:
            logger.error(f"SendGrid email failed to={to_email}: {ex}")
            return False

    elif provider == "smtp":
        def _do_smtp():
            import smtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            host = os.getenv("SMTP_HOST", "smtp.gmail.com")
            port = int(os.getenv("SMTP_PORT", "587"))
            user = os.getenv("SMTP_USER", "")
            pw   = os.getenv("SMTP_PASS", "")
            if not user or not pw:
                raise ValueError("SMTP_USER or SMTP_PASS not set")
            msg = MIMEMultipart("alternative")
            msg["Subject"] = _sanitize_header(subject)
            msg["From"]    = _sanitize_header(from_addr)
            msg["To"]      = _sanitize_header(to_email)
            msg.attach(MIMEText(body_txt, "plain", "utf-8"))
            msg.attach(MIMEText(body_html, "html", "utf-8"))
            with smtplib.SMTP(host, port, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(user, pw)
                server.sendmail(from_addr, [to_email], msg.as_string())
            return True

        try:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(_do_smtp).result(timeout=45)
            logger.info(f"SMTP: email sent to {to_email}")
            return result
        except Exception as ex:
            logger.error(f"SMTP email failed to={to_email}: {ex}")
            return False

    else:
        logger.error(
            f"EMAIL_PROVIDER='{provider}' is not set or unrecognised — "
            f"email to {to_email} was NOT sent. Set EMAIL_PROVIDER=resend in your .env"
        )
        return False


def _send_payment_failed_email(email: str, name: str, day: int) -> bool:
    portal = FRONTEND_URL
    if day == 1:
        subject  = "Action required: Payment failed for your subscription"
        body_txt = (f"Hi {name or 'there'},\n\nWe could not process your payment. "
                    f"Update here: {portal}\n\nThe Team")
        body_html = f"""<div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:24px;">
          <h2 style="color:#1e293b;">Payment failed</h2>
          <p>Hi {name or 'there'},</p><p>We could not process your payment.</p>
          <p><a href="{portal}" style="background:#e6007a;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:600;">Update Billing</a></p>
        </div>"""
    elif day == 7:
        subject  = "Important: Your payment is still overdue"
        body_txt = f"Hi {name or 'there'},\nPayment still outstanding. Update: {portal}"
        body_html = f"""<div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:24px;">
          <h2 style="color:#dc2626;">Payment still overdue</h2>
          <p>Hi {name or 'there'},</p>
          <p style="color:#dc2626;font-weight:bold;">Account will be restricted soon.</p>
          <p><a href="{portal}" style="background:#e6007a;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:600;">Update Billing</a></p>
        </div>"""
    elif day == 10:
        subject  = "Account Disabled: Update Billing"
        body_txt = f"Hi {name or 'there'},\nYour account has been disabled. Please update your billing to restore access: {portal}"
        body_html = f"""<div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:24px;">
          <h2 style="color:#b45309;">Account Disabled</h2>
          <p>Hi {name or 'there'},</p><p>Your account has been disabled. Please update your billing to restore access.</p>
          <p><a href="{portal}" style="background:#e6007a;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:600;">Update Billing</a></p>
        </div>"""
    elif day == 21:
        subject  = "Account suspended: access restricted"
        body_txt = f"Hi {name or 'there'},\nAccount suspended. Update: {portal}"
        body_html = f"""<div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:24px;">
          <h2 style="color:#dc2626;">Account suspended</h2>
          <p>Hi {name or 'there'},</p><p>Suspended — 21 days of non-payment.</p>
          <p><a href="{portal}" style="background:#e6007a;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:600;">Update Billing</a></p>
        </div>"""
    elif day == 60:
        subject  = "Account archived: subscription ended"
        body_txt = (f"Hi {name or 'there'},\nYour account has been archived after 60 days of non-payment. "
                    f"To reactivate, please contact support or update your billing: {portal}")
        body_html = f"""<div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:24px;">
          <h2 style="color:#64748b;">Account Archived</h2>
          <p>Hi {name or 'there'},</p>
          <p>Your account has been archived after 60 days of non-payment. All your data is preserved.</p>
          <p>To reactivate your account, please update your billing details.</p>
          <p><a href="{portal}" style="background:#e6007a;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:600;">Reactivate Account</a></p>
        </div>"""
    else:
        return False
    return _send_generic_email(email, subject, body_txt, body_html)