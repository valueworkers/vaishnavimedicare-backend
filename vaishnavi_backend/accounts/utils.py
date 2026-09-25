from __future__ import annotations

import datetime
from typing import Any

import openpyxl
from django.db import transaction
from django.core.exceptions import ValidationError as DjangoValidationError

from .models import CustomUser, EmployeeProfile, ShiftSchedule 

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

# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

class RowError(Exception):
    """Raised for a single row's validation failure. Caught per-row by
    BulkEmployeeImporter.process_bulk_upload so one bad row never aborts
    the rest of the batch."""

    def __init__(self, errors: dict):
        self.errors = errors
        super().__init__(str(errors))

class BulkEmployeeImporter:
    """
    Usage:
        importer = BulkEmployeeImporter(created_by=request.user)
        rows = importer.parse_workbook(uploaded_file)
        results = importer.process_bulk_upload(rows)
        # results = {"created": [...], "updated": [...], "failed": [...]}
    """

    BOOL_TRUE = {"true", "yes", "1", "y"}

    # Fields that exist on the models but shouldn't be in the bulk sheet:
    # system/auth internals, auto-managed timestamps, and fields with their
    # own dedicated flow (termination via .terminate()/.termination_revoke(),
    # employee_id is auto-generated, rehired_status follows from that flow).
    EXCLUDED_USER_FIELDS = {
        "id", "password", "last_login", "is_superuser", "is_staff", "is_active",
        "is_deleted", "profile_pic",
    }
    EXCLUDED_PROFILE_FIELDS = {
        "id", "created_at", "updated_at",
        "termination_type", "termination_reason", "last_working_day",
        "employee_id", "rehired_status",
    }

    MAX_ROWS = 2000

    _MISSING = object()  # sentinel: cell was blank, distinct from a real empty string

    def __init__(self, created_by: CustomUser):
        self.created_by = created_by
        self.user_fields = {f.name: f for f in self._iter_fields(CustomUser, self.EXCLUDED_USER_FIELDS)}
        self.profile_fields = {f.name: f for f in self._iter_fields(EmployeeProfile, self.EXCLUDED_PROFILE_FIELDS)}
        self.columns = self._build_columns()
        self.required_on_create = {c[0] for c in self.columns if c[2] == "user" and c[3]}

    # ------------------------------------------------------------------
    # Column specification — derived from the models, not hand-typed
    # ------------------------------------------------------------------
    @staticmethod
    def _iter_fields(model, excluded_names):
        """Concrete, non-relational, non-auto fields on a model, minus excluded_names.
        Relations (FK/O2O/reverse) are deliberately skipped — the one relation we
        care about (EmployeeProfile.shift) is handled by hand below, since a bulk
        sheet needs a human-readable lookup, not a raw FK id."""
        for f in model._meta.get_fields():
            if not getattr(f, "concrete", False) or f.auto_created or f.is_relation:
                continue
            if f.name in excluded_names:
                continue
            yield f

    @staticmethod
    def _humanize_header(field) -> str:
        label = getattr(field, "verbose_name", None) or field.name.replace("_", " ")
        return str(label).strip().title()

    @staticmethod
    def _field_required(field) -> bool:
        if field.has_default():
            return False
        return not field.blank

    @staticmethod
    def _type_hint(field) -> str:
        """A short format hint for the header, read off the field's own type —
        choice fields already get their options listed in the help text instead."""
        if getattr(field, "choices", None):
            return ""
        internal = field.get_internal_type()
        if internal == "BooleanField":
            return " (TRUE/FALSE)"
        if internal in ("DateField", "DateTimeField"):
            return " (YYYY-MM-DD)"
        if internal == "JSONField":
            return " (comma separated)"
        return ""

    @staticmethod
    def _field_help(field) -> str:
        parts = []
        if getattr(field, "help_text", None):
            parts.append(str(field.help_text))
        choices = getattr(field, "choices", None)
        if choices:
            parts.append("Options: " + " / ".join(c[0] for c in choices))
        for v in getattr(field, "validators", []):
            message = getattr(v, "message", None)
            if message and "regex" in type(v).__name__.lower():
                parts.append(str(message))
        return " ".join(parts)

    def _build_columns(self):
        columns = [
            # key             header                          target  required  help
            ("action",        "Action (Create/Update)",       "meta", False, "Leave blank to auto-detect from Mobile Number / Employee ID"),
            ("employee_id",   "Employee ID",                   "meta", False, "Required to UPDATE an existing employee's profile fields. Leave blank when creating — it is generated automatically."),
        ]
        for key, field in self.user_fields.items():
            required = self._field_required(field)
            header = self._humanize_header(field) + self._type_hint(field) + ("*" if required else "")
            columns.append((key, header, "user", required, self._field_help(field)))
        for key, field in self.profile_fields.items():
            header = self._humanize_header(field) + self._type_hint(field)
            columns.append((key, header, "profile", False, self._field_help(field)))
        # EmployeeProfile.shift is a FK — expose it as a name lookup, not a raw id
        columns.append(("shift_name", "Shift Name", "profile", False, "Must match an existing Shift Schedule name; leave blank if none"))
        return columns

    # ------------------------------------------------------------------
    # Parsing uploaded workbook -> list[dict]
    # ------------------------------------------------------------------
    def parse_workbook(self, file_obj) -> list[dict[str, Any]]:
        wb = openpyxl.load_workbook(file_obj, data_only=True)
        sheet = wb["Employees"] if "Employees" in wb.sheetnames else wb.active

        header_row = [c.value for c in sheet[1]]
        # map header text -> key, tolerant of the trailing "*"
        header_to_key = {}
        for key, header, *_ in self.columns:
            header_to_key[header] = key
            header_to_key[header.rstrip("*").strip()] = key

        col_index_to_key = {}
        for idx, header in enumerate(header_row):
            if header is None:
                continue
            k = header_to_key.get(str(header).strip())
            if k:
                col_index_to_key[idx] = k

        rows = []
        for row_num, raw_row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            if all(v in (None, "") for v in raw_row):
                continue
            row_dict = {"_row_num": row_num}
            for idx, value in enumerate(raw_row):
                key = col_index_to_key.get(idx)
                if not key:
                    continue
                if isinstance(value, datetime.datetime):
                    value = value.date()
                row_dict[key] = value
            print(row_dict)
            rows.append(row_dict)
        return rows

    # ------------------------------------------------------------------
    # Value cleaning helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _clean_str(v) -> str:
        if v is None:
            return ""
        return str(v).strip()

    @classmethod
    def _clean_bool(cls, v) -> bool:
        return cls._clean_str(v).lower() in cls.BOOL_TRUE

    @classmethod
    def _clean_date(cls, v, field_name: str):
        if v in (None, ""):
            return None
        if isinstance(v, datetime.date):
            return v
        try:
            return datetime.datetime.strptime(cls._clean_str(v), "%Y-%m-%d").date()
        except ValueError:
            raise RowError({field_name: f"'{v}' is not a valid date (expected YYYY-MM-DD)."})

    @classmethod
    def _coerce_value(cls, field, raw, key):
        """Turn a raw cell value into the python value its model field expects,
        reading the target type/choices straight off the field. Returns _MISSING
        for a blank cell so callers can tell "not provided" apart from "cleared"."""
        raw_str = cls._clean_str(raw)
        if raw_str == "":
            return cls._MISSING

        choices = getattr(field, "choices", None)
        if choices:
            raw_str = raw_str.upper()
            valid = {c[0] for c in choices}
            if raw_str not in valid:
                raise RowError({key: f"Must be one of {sorted(valid)}."})
            return raw_str

        internal = field.get_internal_type()
        if internal == "BooleanField":
            return cls._clean_bool(raw)
        if internal in ("DateField", "DateTimeField"):
            return cls._clean_date(raw, key)
        if internal in ("IntegerField", "PositiveIntegerField", "PositiveSmallIntegerField", "SmallIntegerField", "BigIntegerField"):
            try:
                return int(raw_str)
            except ValueError:
                raise RowError({key: f"'{raw}' is not a valid integer."})
        if internal == "FloatField":
            try:
                return float(raw_str)
            except ValueError:
                raise RowError({key: f"'{raw}' is not a valid number."})
        if internal == "JSONField":
            return [s.strip() for s in raw_str.split(",") if s.strip()]
        return raw_str  # CharField / TextField / EmailField and friends

    # ------------------------------------------------------------------
    # Row-level validation + apply
    # ------------------------------------------------------------------
    @staticmethod
    def _find_existing_user(row: dict) -> CustomUser | None:
        employee_id = BulkEmployeeImporter._clean_str(row.get("employee_id"))
        mobile_number = BulkEmployeeImporter._clean_str(row.get("mobile_number"))

        if employee_id:
            profile = EmployeeProfile.objects.filter(employee_id=employee_id).select_related("user").first()
            if profile:
                return profile.user
        if mobile_number:
            return CustomUser.objects.filter(mobile_number=mobile_number).first()
        return None

    def process_row(self, row: dict) -> dict:
        """
        Validate and apply a single row. Raises RowError on validation failure.
        Returns {"status": "created"|"updated", "employee_id": ..., "mobile_number": ...}
        Wrapped in its own transaction/savepoint so one bad row can't roll back
        the rest of the batch.
        """
        action = self._clean_str(row.get("action")).lower()
        existing_user = self._find_existing_user(row)
    
        if action == "create" and existing_user:
            raise RowError({"action": "Action was 'create' but a user matching Employee ID / Mobile Number already exists."})
        if action == "update" and not existing_user:
            raise RowError({"action": "Action was 'update' but no existing user matches Employee ID / Mobile Number."})

        is_update = bool(existing_user) if action == "" else (action == "update")

        errors: dict[str, str] = {}
        cleaned_user: dict[str, Any] = {}
        cleaned_profile: dict[str, Any] = {}

        for key, field in self.user_fields.items():
            try:
                value = self._coerce_value(field, row.get(key), key)
            except RowError as e:
                errors.update(e.errors)
                continue
            if value is self._MISSING:
                if not is_update and key in self.required_on_create:
                    errors[key] = "Required."
                continue
            cleaned_user[key] = value

        for key, field in self.profile_fields.items():
            try:
                value = self._coerce_value(field, row.get(key), key)
            except RowError as e:
                errors.update(e.errors)
                continue
            if value is self._MISSING:
                continue
            cleaned_profile[key] = value

        if errors:
            raise RowError(errors)

        shift = None
        shift_name = self._clean_str(row.get("shift_name"))
        if shift_name:
            shift = ShiftSchedule.objects.filter(name=shift_name).first()
            if not shift:
                raise RowError({"shift_name": f"No Shift Schedule named '{shift_name}' exists."})

        with transaction.atomic():
            if is_update:
                user = existing_user
                for key, value in cleaned_user.items():
                    setattr(user, key, value)
            else:
                user = CustomUser(created_by=self.created_by, **cleaned_user)
                user.set_unusable_password()  # bulk-created users reset their password via invite flow

            try:
                user.full_clean(exclude=["password"])
            except DjangoValidationError as e:
                raise RowError(e.message_dict)
            user.save()

            profile, _ = EmployeeProfile.objects.get_or_create(user=user)
            for key, value in cleaned_profile.items():
                setattr(profile, key, value)
            if shift_name:
                profile.shift = shift

            try:
                profile.full_clean()
            except DjangoValidationError as e:
                raise RowError(e.message_dict)
            profile.save()

        return {
            "status": "updated" if is_update else "created",
            "employee_id": profile.employee_id,
            "mobile_number": user.mobile_number,
            "full_name": user.get_full_name(),
        }

    def process_bulk_upload(self, rows: list[dict]) -> dict:
        results = {"created": [], "updated": [], "failed": []}
        for row in rows:
            row_num = row.get("_row_num")
            try:
                outcome = self.process_row(row)
                results[outcome["status"]].append({"row": row_num, **outcome})
            except RowError as e:
                results["failed"].append({"row": row_num, "errors": e.errors})
            except DjangoValidationError as e:
                results["failed"].append({"row": row_num, "errors": e.message_dict if hasattr(e, "message_dict") else {"__all__": e.messages}})
            except Exception as e:  # noqa: BLE001 — surface unexpected errors per-row instead of failing the whole batch
                results["failed"].append({"row": row_num, "errors": {"__all__": str(e)}})
        return results

