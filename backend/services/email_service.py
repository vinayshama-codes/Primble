import os
import json
import logging
from config.settings import STRIPE_BILLING_PORTAL_URL

logger = logging.getLogger(__name__)


def send_verification_email(email: str, code: str) -> bool:
    provider  = os.getenv("EMAIL_PROVIDER", "").lower()
    from_addr = os.getenv("EMAIL_FROM", "noreply@acordly.ai")
    subject   = "Your Acordly Verification Code"
    body_txt  = f"Your Acordly verification code is: {code}\n\nExpires in 10 minutes."
    body_html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:24px;">
      <h2 style="color:#1e293b;">Verify your Acordly account</h2>
      <p style="color:#475569;">Enter the code below to complete sign-up.</p>
      <div style="background:#f1f5f9;border-radius:8px;padding:24px;text-align:center;margin-bottom:24px;">
        <span style="font-size:36px;font-weight:700;letter-spacing:8px;color:#0f172a;">{code}</span>
      </div>
      <p style="color:#64748b;font-size:13px;">Expires in <strong>10 minutes</strong>.</p>
    </div>
    """
    return _send_generic_email(email, subject, body_txt, body_html, provider, from_addr)


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

    if provider == "resend":
        try:
            import urllib.request
            api_key = os.getenv("RESEND_API_KEY", "")
            if not api_key:
                logger.error("RESEND_API_KEY not set")
                return False
            payload = json.dumps({"from": from_addr, "to": [to_email], "subject": subject, "html": body_html, "text": body_txt}).encode()
            req = urllib.request.Request(
                "https://api.resend.com/emails", data=payload,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=10):
                return True
        except Exception as ex:
            logger.error(f"Resend email failed: {ex}")
            return False

    elif provider == "sendgrid":
        try:
            import urllib.request
            api_key = os.getenv("SENDGRID_API_KEY", "")
            if not api_key:
                return False
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
                return True
        except Exception as ex:
            logger.error(f"SendGrid email failed: {ex}")
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
            msg["Subject"] = subject
            msg["From"]    = from_addr
            msg["To"]      = to_email
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
                return pool.submit(_do_smtp).result(timeout=45)
        except Exception as ex:
            logger.error(f"SMTP failed: {ex}")
            return False

    else:
        logger.warning(f"EMAIL_PROVIDER not set — code for {to_email} not sent")
        return True


def _send_payment_failed_email(email: str, name: str, day: int) -> bool:
    portal = STRIPE_BILLING_PORTAL_URL
    if day == 1:
        subject  = "Action required: Payment failed for your Acordly subscription"
        body_txt = (f"Hi {name or 'there'},\n\nWe could not process your payment. "
                    f"Update here: {portal}\n\nThe Acordly Team")
        body_html = f"""<div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:24px;">
          <h2 style="color:#1e293b;">Payment failed</h2>
          <p>Hi {name or 'there'},</p><p>We could not process your Acordly payment.</p>
          <p><a href="{portal}" style="background:#e6007a;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:600;">Update Billing</a></p>
        </div>"""
    elif day == 7:
        subject  = "Important: Your Acordly payment is still overdue"
        body_txt = f"Hi {name or 'there'},\nPayment still outstanding. Update: {portal}"
        body_html = f"""<div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:24px;">
          <h2 style="color:#dc2626;">Payment still overdue</h2>
          <p>Hi {name or 'there'},</p>
          <p style="color:#dc2626;font-weight:bold;">Account will be restricted soon.</p>
          <p><a href="{portal}" style="background:#e6007a;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:600;">Update Billing</a></p>
        </div>"""
    elif day == 10:
        subject  = "Account Disabled: Update Billing"
        body_txt = f"Hi {name or 'there'},\nAccount disabled. Update: {portal}"
        body_html = f"""<div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:24px;">
          <h2 style="color:#b45309;">Account Disabled</h2>
          <p>Hi {name or 'there'},</p><p>Your account is disabled — 10 days overdue.</p>
          <p><a href="{portal}" style="background:#e6007a;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:600;">Update Billing</a></p>
        </div>"""
    elif day == 21:
        subject  = "Account suspended: Acordly access restricted"
        body_txt = f"Hi {name or 'there'},\nAccount suspended. Update: {portal}"
        body_html = f"""<div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:24px;">
          <h2 style="color:#dc2626;">Account suspended</h2>
          <p>Hi {name or 'there'},</p><p>Suspended — 21 days of non-payment.</p>
          <p><a href="{portal}" style="background:#e6007a;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:600;">Update Billing</a></p>
        </div>"""
    else:
        return False
    return _send_generic_email(email, subject, body_txt, body_html)