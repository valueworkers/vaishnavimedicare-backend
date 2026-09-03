from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings

import hashlib
import random
import uuid
import json
from django.core.cache import cache

# Lazy client — avoids crash at import time if env vars are missing
def _twilio_client():
    return Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)


def send_sms(user, otp):
    _twilio_client().messages.create(
        body=f"Your OTP is {otp}. Valid for 10 minutes. Do not share it.",
        from_=settings.TWILIO_PHONE_NUMBER,
        to=user.mobile_number,
    )


def send_whatsapp(user, otp):
    phone = user.mobile_number
    if not phone.startswith("+"):
        phone = f"+91{phone}"

    _twilio_client().messages.create(
        body=f"Your OTP is {otp}. Valid for 10 minutes. Do not share it.",
        from_=settings.TWILIO_WHATSAPP_NUMBER,
        to=f"whatsapp:{phone}",
    )


def send_email(user, otp):
    display_name = user.first_name or user.email
    subject = f"Your OTP for Password Reset: {otp}"

    html_content = render_to_string(
        "emails/otp_email.html",
        {"user_name": display_name, "otp_code": str(otp)},
    )

    email = EmailMultiAlternatives(
        subject=subject,
        body=(
            f"Hi {display_name},\n\n"
            f"Your OTP for password reset is: {otp}\n\n"
            f"This code is valid for 10 minutes.\n"
            f"If you didn't request this, please ignore this email."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    email.attach_alternative(html_content, "text/html")
    email.send()


CHANNEL_HANDLERS = {
    "sms":      send_sms,
    "whatsapp": send_whatsapp,
    "email":    send_email,
}


class UnsupportedChannel(Exception):
    pass


def send_otp(channel: str, user, raw_otp: str) -> None:
    handler = CHANNEL_HANDLERS.get(channel)
    if handler is None:
        raise UnsupportedChannel(f"Unknown OTP channel: {channel!r}")
    handler(user, raw_otp) 
    

OTP_TTL     = 60 * 10       # 10 minutes
TOKEN_TTL   = 60 * 15       # 15 minutes for reset token


def _otp_key(user_id):
    return f"pwd_reset:otp:{user_id}"

def _token_key(token):
    return f"pwd_reset:token:{token}"


class InvalidOTP(Exception):
    pass

class ExpiredOTP(Exception):
    pass

class TooManyAttempts(Exception):
    pass


class PasswordResetOTP:
    """Stateless Redis-backed OTP — no DB table."""

    # ---- exceptions (same interface as before) ----
    InvalidOTP    = InvalidOTP
    ExpiredOTP    = ExpiredOTP
    TooManyAttempts = TooManyAttempts

    @classmethod
    def generate(cls, user) -> str:
        # raw = f"{random.SystemRandom().randint(0, 999999):06d}"
        raw = f"000000" # For testing, fixed OTP. Change to above line for production.
        payload = {
            "hash":         hashlib.sha256(raw.encode()).hexdigest(),
            "otp":  raw,
        }
        # Overwrites any existing OTP — old one instantly dead
        cache.set(_otp_key(user.id), json.dumps(payload), timeout=OTP_TTL)
        return raw

    @classmethod
    def verify(cls, user, raw_otp) -> str:
        """
        Validates OTP. Returns a reset token (UUID str) on success.
        Raises InvalidOTP / ExpiredOTP.
        """
        key     = _otp_key(user.id)
        raw_val = cache.get(key)

        if raw_val is None:
            raise cls.ExpiredOTP()

        payload = json.loads(raw_val)

        if payload.get("otp") != raw_otp:
            raise cls.InvalidOTP()

        if payload["hash"] != hashlib.sha256(raw_otp.encode()).hexdigest():
            raise cls.InvalidOTP()

        # Mark verified so the same OTP can't be reused
        cache.set(key, json.dumps(payload), timeout=OTP_TTL)

        return cls._issue_reset_token(user)

    @classmethod
    def _issue_reset_token(cls, user) -> str:
        token = str(uuid.uuid4())
        cache.set(_token_key(token), user.id, timeout=TOKEN_TTL)
        return token

    @classmethod
    def consume_reset_token(cls, token) -> int:
        """
        Called during the final password-change step.
        Returns user_id and deletes the token (one-time use).
        Raises InvalidOTP if missing/expired.
        """
        key     = _token_key(token)
        user_id = cache.get(key)

        if user_id is None:
            raise cls.InvalidOTP()

        cache.delete(key)   # one-time use
        return user_id