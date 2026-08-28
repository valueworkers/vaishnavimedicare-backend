from django.utils.safestring import mark_safe
from django.utils.html import format_html
from django.contrib import admin
from .models import (
    Location,
    Package,
    Patient,
    PrimaryOrder,
    SecondaryOrder,
    TernaryOrder,
    TotalInvoice,
    Payment,
)

# Location
@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("building_name", "city", "state", "location_type", "user")
    list_filter = ("location_type", "city", "state")
    search_fields = ("building_name", "city", "state", "postal_code")
    autocomplete_fields = ("user",)

# Package
@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "package_type", "period", "price","registration_fees", "is_active", "created_at")
    list_filter = ("package_type", "period", "is_active")
    search_fields = ("name", "owner__email")
    autocomplete_fields = ("owner",)
    readonly_fields = ("created_at", "updated_at")

# Patient
@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ("patient_id", "first_name", "last_name", "phone", "gender", "registration_date","is_registration_fees_paid")
    list_filter = ("gender", "blood_group", "registration_date")
    search_fields = ("patient_id", "first_name", "last_name", "phone", "email")
    autocomplete_fields = ("registered_by",)
    readonly_fields = ("patient_id", "registration_date", "updated_at")
    date_hierarchy = "registration_date"

# ── Inlines ────────────────────────────────────────────────────────────────────
class SecondaryOrderInline(admin.TabularInline):
    model = SecondaryOrder
    extra = 0
    readonly_fields = (
        "order_id", "start_datetime", "end_datetime",
        "subtotal", "status", "created_at",
    )
    fields = (
        "order_id", "start_datetime", "end_datetime",
        "subtotal", "is_registration_fee", "status", "created_at",
    )
    show_change_link = True
    can_delete = False
    ordering = ["start_datetime"]

class TernaryOrderInline(admin.TabularInline):
    model = TernaryOrder
    extra = 0
    readonly_fields = (
        "order_id", "service", "package", "booking_type",
        "start_datetime", "end_datetime",
        "discount_amount", "premium_amount", "subtotal",
        "status", "created_at",
    )
    fields = readonly_fields
    show_change_link = True
    can_delete = False
    ordering = ["start_datetime"]

class TotalInvoiceInline(admin.TabularInline):
    model = TotalInvoice
    fk_name = "secondary_order"
    extra = 0
    readonly_fields = (
        "invoice_number", "period_start", "period_end",
        "subtotal", "total_amount", "paid_amount",
        "remaining_amount", "status", "due_date",
    )
    fields = readonly_fields
    show_change_link = True
    can_delete = False

class TernaryInvoiceInline(admin.TabularInline):
    """Child (ternary) invoices shown inside a Secondary invoice."""
    model = TotalInvoice
    fk_name = "parent_invoice"
    verbose_name = "Ternary Invoice"
    verbose_name_plural = "Ternary Invoices"
    extra = 0
    readonly_fields = (
        "invoice_number", "ternary_order", "period_start", "period_end",
        "subtotal", "discount_amount", "premium_amount",
        "total_amount", "paid_amount", "remaining_amount", "status",
    )
    fields = readonly_fields
    show_change_link = True
    can_delete = False

class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ("reference", "paid_date", "is_verified", "created_at")
    fields = ("amount", "method", "reference", "paid_date", "is_verified", "created_at")
    ordering = ["-paid_date"]

# ── PrimaryOrder ───────────────────────────────────────────────────────────────
@admin.register(PrimaryOrder)
class PrimaryOrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_id", "patient", "booking_entity_badge",
        "venue", "service", "package",
        "start_datetime", "end_datetime",
        "booking_type", "status_badge",
        "total_bill", "created_at",
    )
    list_filter = (
        "status", "booking_entity", "booking_type",
        "auto_continue", "created_at"
    )
    search_fields = (
        "order_id", "patient__first_name", "patient__last_name",
        "user__email", "venue__name", "service__name","status"
    )
    readonly_fields = (
        "order_id", "total_bill", "booking_type",
        "created_at", "updated_at",
    )
    fieldsets = (
        ("Identifiers", {
            "fields": ("order_id",),
        }),
        ("Booking Details", {
            "fields": (
                "booking_entity", "user", "patient",
                "venue", "service", "package",
                "booking_type", "auto_continue","client_address"
            ),
        }),
        ("Schedule", {
            "fields": ("start_datetime", "end_datetime"),
        }),
        ("Financials", {
            "fields": ("total_bill",'discount_amount','premium_amount'),
        }),
        ("Status & Timestamps", {
            "fields": ("status", "created_at", "updated_at"),
        }),
    )
    inlines = [SecondaryOrderInline]
    date_hierarchy = "created_at"
    ordering = ["-created_at"]
    list_per_page = 30

    @admin.display(description="Entity")
    def booking_entity_badge(self, obj):
        colors = {"VENUE": "#6366f1", "SERVICE": "#0ea5e9"}
        color = colors.get(obj.booking_entity, "#6b7280")
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:11px">{}</span>',
            color, obj.get_booking_entity_display(),
        )

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {
            "LOBBY": "#9ca3af",
            "UPCOMING": "#3b82f6",
            "ONGOING": "#f59e0b",
            "COMPLETED": "#10b981",
            "CANCELLED": "#ef4444",
        }
        color = colors.get(obj.status, "#6b7280")
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:11px">{}</span>',
            color, obj.status,
        )

    actions = ["recalculate_totals"]

    @admin.action(description="Recalculate total bills")
    def recalculate_totals(self, request, queryset):
        for order in queryset:
            order.recalculate_total()
        self.message_user(request, f"Recalculated totals for {queryset.count()} orders.")

# ── SecondaryOrder ─────────────────────────────────────────────────────────────
@admin.register(SecondaryOrder)
class SecondaryOrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_id", "primary_order_link", "start_datetime",
        "end_datetime", "subtotal", "status_badge", "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = (
        "order_id",
        "primary_order__order_id",
        "primary_order__patient__first_name",
        "primary_order__patient__last_name",
        "status"
    )
    readonly_fields = (
        "order_id", "subtotal", 
        "created_at", "updated_at",
    )
    fieldsets = (
        ("Identifiers", {
            "fields": ("order_id", "primary_order"),
        }),
        ("Schedule", {
            "fields": ("start_datetime", "end_datetime"),
        }),
        ("Financials", {
            "fields": ("subtotal",),
        }),
        ("Status & Timestamps", {
            "fields": ("status","status_locked", "created_at", "updated_at"),
        }),
    )
    inlines = [TernaryOrderInline, TotalInvoiceInline]
    date_hierarchy = "start_datetime"
    ordering = ["-start_datetime"]
    list_per_page = 30

    @admin.display(description="Primary Order", ordering="primary_order__order_id")
    def primary_order_link(self, obj):
        if obj.primary_order_id:
            return format_html(
                '<a href="/admin/booking/primaryorder/{}/change/">{}</a>',
                obj.primary_order_id, obj.primary_order.order_id,
            )
        return "—"

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {
            "LOBBY": "#9ca3af", "UPCOMING": "#3b82f6",
            "ONGOING": "#f59e0b", "COMPLETED": "#10b981",
            "CANCELLED": "#ef4444",
        }
        color = colors.get(obj.status, "#6b7280")
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:11px">{}</span>',
            color, obj.status,
        )

    actions = ["recalculate_subtotals"]

    @admin.action(description="Recalculate subtotals")
    def recalculate_subtotals(self, request, queryset):
        for order in queryset:
            order.recalculate_subtotal()
        self.message_user(request, f"Recalculated subtotals for {queryset.count()} secondary orders.")

# ── TernaryOrder ───────────────────────────────────────────────────────────────
@admin.register(TernaryOrder)
class TernaryOrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_id", "secondary_order", "service", "package",
        "start_datetime", "end_datetime",
        "discount_amount", "premium_amount", "subtotal",
        "status_badge", "created_at",
    )
    list_filter = ("status", "booking_entity", "booking_type", "created_at")
    search_fields = (
        "order_id",
        "secondary_order__order_id",
        "secondary_order__primary_order__order_id",
        "service__name",
    )
    readonly_fields = (
        "order_id", "subtotal", "booking_type",
        "created_at", "updated_at",
    )
    fieldsets = (
        ("Identifiers", {
            "fields": ("order_id", "secondary_order"),
        }),
        ("Service / Package", {
            "fields": ("service", "package", "booking_entity", "booking_type","client_address"),
        }),
        ("Schedule", {
            "fields": ("start_datetime", "end_datetime"),
        }),
        ("Financials", {
            "fields": ("discount_amount", "premium_amount", "subtotal"),
        }),
        ("Status & Timestamps", {
            "fields": ("status", "created_at", "updated_at"),
        }),
    )
    date_hierarchy = "start_datetime"
    ordering = ["-start_datetime"]
    list_per_page = 30

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {
            "LOBBY": "#9ca3af", "UPCOMING": "#3b82f6",
            "ONGOING": "#f59e0b", "COMPLETED": "#10b981",
            "CANCELLED": "#ef4444",
        }
        color = colors.get(obj.status, "#6b7280")
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:11px">{}</span>',
            color, obj.status,
        )

# ── TotalInvoice ───────────────────────────────────────────────────────────────
@admin.register(TotalInvoice)
class TotalInvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "invoice_number", "invoice_type_badge", "patient", "user",
        "period_start", "period_end",
        "subtotal", "discount_amount", "premium_amount",
        "tax_amount", "total_amount",
        "paid_amount", "remaining_amount",
        "status_badge", "due_date", "issued_date",
    )
    list_filter = ("status", "issued_date", "due_date")
    search_fields = (
        "invoice_number",
        "patient__first_name", "patient__last_name",
        "user__email",
        "secondary_order__order_id",
        "ternary_order__order_id",
    )
    readonly_fields = (
        "invoice_number", "invoice_type",
        "subtotal", "total_amount", "paid_amount",
        "remaining_amount", "issued_date",
        "created_at", "updated_at",
    )
    fieldsets = (
        ("Identifiers", {
            "fields": ("invoice_number", "invoice_type"),
        }),
        ("Linked Orders", {
            "fields": ("secondary_order", "ternary_order", "parent_invoice"),
        }),
        ("Patient & User", {
            "fields": ("patient", "user"),
        }),
        ("Period", {
            "fields": ("period_start", "period_end"),
        }),
        ("Financials", {
            "fields": (
                "subtotal", "discount_amount", "premium_amount",
                "tax_amount", "total_amount",
                "paid_amount", "remaining_amount",
            ),
        }),
        ("Status & Dates", {
            "fields": ("status", "due_date", "issued_date", "created_at", "updated_at"),
        }),
    )
    inlines = [PaymentInline, TernaryInvoiceInline]
    date_hierarchy = "issued_date"
    ordering = ["-issued_date"]
    list_per_page = 30

    @admin.display(description="Type")
    def invoice_type_badge(self, obj):
        if obj.secondary_order_id:
            color, label = "#6366f1", "SECONDARY"
        else:
            color, label = "#0ea5e9", "TERNARY"
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:11px">{}</span>',
            color, label,
        )

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {
            "UNPAID": "#ef4444",
            "PARTIALLY_PAID": "#f59e0b",
            "PAID": "#10b981",
        }
        color = colors.get(obj.status, "#6b7280")
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:11px">{}</span>',
            color, obj.status,
        )

    actions = ["recalculate_totals", "recalculate_payments"]

    @admin.action(description="Recalculate invoice totals")
    def recalculate_totals(self, request, queryset):
        for inv in queryset:
            inv.recalculate_totals()
        self.message_user(request, f"Recalculated totals for {queryset.count()} invoices.")

    @admin.action(description="Recalculate payments & status")
    def recalculate_payments(self, request, queryset):
        for inv in queryset:
            inv.recalculate_payments()
        self.message_user(request, f"Recalculated payments for {queryset.count()} invoices.")

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "invoice_link",
        "patient_display",
        "amount",
        "method",
        "reference",
        "paid_date",
        "verified_badge",
        "created_at",
    )

    list_filter = ("method", "is_verified", "paid_date")

    search_fields = (
        "reference",
        "invoice__invoice_number",
        "patient__first_name",
        "patient__last_name",
    )

    readonly_fields = ("reference", "created_at")

    fieldsets = (
        ("Invoice", {
            "fields": ("invoice", "patient"),
        }),
        ("Payment Details", {
            "fields": ("amount", "method", "reference", "paid_date"),
        }),
        ("Verification", {
            "fields": ("is_verified",),
        }),
        ("Timestamps", {
            "fields": ("created_at",),
        }),
    )

    date_hierarchy = "paid_date"
    ordering = ["-paid_date"]
    list_per_page = 30

    # ── Custom Displays ─────────────────────────────────────────────

    @admin.display(description="Invoice", ordering="invoice__invoice_number")
    def invoice_link(self, obj):
        invoice = getattr(obj, "invoice", None)

        if not invoice:
            return mark_safe('<span style="color:red;">Unmapped</span>')

        invoice_number = getattr(invoice, "invoice_number", None) or "Unmapped"

        return format_html(
            '<a href="/admin/orders/totalinvoice/{}/change/">{}</a>',
            obj.invoice_id,
            invoice_number,
        )
    
    @admin.display(description="Patient", ordering="patient__first_name")
    def patient_display(self, obj):
        if not obj.patient:
            return mark_safe('<span style="color:red;">Unmapped</span>')
        return str(obj.patient)

    @admin.display(description="Verified", boolean=True)
    def verified_badge(self, obj):
        return obj.is_verified

    # ── Actions ────────────────────────────────────────────────────

    actions = ["verify_payments", "unverify_payments"]

    @admin.action(description="Mark selected payments as verified")
    def verify_payments(self, request, queryset):
        count = 0
        for p in queryset:
            if p.verify():
                count += 1
        self.message_user(request, f"Verified {count} payment(s).")

    @admin.action(description="Mark selected payments as unverified")
    def unverify_payments(self, request, queryset):
        count = 0
        for p in queryset:
            if p.unverify():
                count += 1
        self.message_user(request, f"Unverified {count} payment(s).")