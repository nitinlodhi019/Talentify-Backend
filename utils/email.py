import os
import random

def generate_otp():
    return str(random.randint(100000, 999999))

def send_otp_email(to_email, otp):
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    sender_email = os.environ.get("SMTP_USER", 'your_email@gmail.com')
    sender_pass = os.environ.get("SMTP_PASS", 'your_app_password')

    if not sender_email or not sender_pass:
        print("SMTP_USER or SMTP_PASS environment variables not set. Email sending skipped.")
        return

    # Create message
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "🔐 Your OTP for Resume Screening Verification"
    msg["From"] = sender_email
    msg["To"] = to_email

    text = f"""\
Hi,

Your OTP for Resume Screening verification is: {otp}

This OTP is valid for 10 minutes. Do not share it with anyone.

If you did not request this, please ignore this email.

Thanks,
Resume Screening Team
"""

    html = f"""\
<html>
  <body style="font-family: Arial, sans-serif; background-color: #f9f9f9; padding: 20px;">
    <div style="max-width: 600px; margin: auto; background-color: #ffffff; border-radius: 8px; padding: 30px; box-shadow: 0px 0px 10px rgba(0,0,0,0.1);">
      <h2 style="color: #2e86de;">🔐 Resume Screening OTP Verification</h2>
      <p>Hi there,</p>
      <p>Your One-Time Password (OTP) for verifying your email address is:</p>
      <h1 style="color: #27ae60; letter-spacing: 4px;">{otp}</h1>
      <p>This OTP is valid for <strong>10 minutes</strong>. Please do not share it with anyone.</p>
      <hr style="margin: 30px 0;">
      <p style="font-size: 0.9em; color: #888888;">
        If you did not request this email, you can safely ignore it.<br>
        Need help? Contact us at <a href="mailto:nitin.renusharmafoundation@gmail.com">nitin.renusharmafoundation@gmail.com</a>
      </p>
      <p style="font-size: 0.9em; color: #888888;">Thanks,<br>The Resume Screening Team</p>
    </div>
  </body>
</html>
"""

    #attach plain and html part
    part1 = MIMEText(text, "plain")
    part2 = MIMEText(html, "html")
    msg.attach(part1)
    msg.attach(part2)

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender_email, sender_pass)
            server.send_message(msg)
        print(f"✅ OTP sent to {to_email}")
    except Exception as e:
        print(f"❌ Failed to send OTP email to {to_email}: {e}")
