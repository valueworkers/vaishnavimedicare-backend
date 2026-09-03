from django.contrib import admin
from django.contrib.contenttypes.admin import GenericTabularInline
from .models import Venue, Service, Resource, Photos


# -------------------- Generic Photo Inline --------------------

class PhotoInline(GenericTabularInline):
    model = Photos
    extra = 1
    fields = ("image", "is_primary", "uploaded_at")
    readonly_fields = ("uploaded_at",)


# -------------------- Venue Admin --------------------
@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "owner",
        "capacity",
        "is_active",
        "is_deleted",
        "created_at",
    )
    list_filter = ("is_active", "is_deleted", "created_at")
    search_fields = ("name", "owner__email", "owner__first_name")
    autocomplete_fields = ("owner",)
    filter_horizontal = ("manager", "staff")
    inlines = [PhotoInline]

    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        ("Basic Info", {
            "fields": ("name", "description", "logo", "location")
        }),
        ("Ownership", {
            "fields": ("owner", "manager", "staff")
        }),
        ("Contact Info", {
            "fields": ("contact", "website", "social_links")
        }),
        ("Capacity & Pricing", {
            "fields": ("capacity", "price_per_event", "rooms", "floors")
        }),
        ("Settings", {
            "fields": (
                "parking_slots",
                "external_decorators_allow",
                "external_caterers_allow",
                "amenities",
                "seating_arrangement",
                "is_active",
                "is_deleted",
            )
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at")
        }),
    )


# -------------------- Service Admin --------------------

@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "owner",
        "city",
        "is_active",
        "is_deleted",
        "created_at",
    )
    list_filter = ("city", "is_active", "is_deleted")
    search_fields = ("name", "city", "owner__email")
    autocomplete_fields = ("owner",)
    filter_horizontal = ("manager", "staff", "venue")
    inlines = [PhotoInline]

    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        ("Basic Info", {
            "fields": ("name", "description", "logo")
        }),
        ("Ownership", {
            "fields": ("owner", "manager", "staff")
        }),
        ("Location", {
            "fields": ("address", "city", "venue")
        }),
        ("Contact", {
            "fields": ("contact", "website")
        }),
        ("Extra Info", {
            "fields": ("tags", "quick_info", "is_active", "is_deleted")
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at")
        }),
    )


# -------------------- Resource Admin --------------------

@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "owner",
        "total_quantity",
        "available_quantity",
        "is_active",
        "created_at",
    )
    list_filter = ("is_active", "created_at")
    search_fields = ("name", "owner__email")
    autocomplete_fields = ("owner", "venue", "service")
    filter_horizontal = ("manager", "staff")
    inlines = [PhotoInline]

    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        ("Basic Info", {
            "fields": ("name", "description", "address")
        }),
        ("Ownership", {
            "fields": ("owner", "manager", "staff")
        }),
        ("Inventory", {
            "fields": (
                "total_quantity",
                "available_quantity",
                "sell_price_per_unit",
                "rent_price_per_unit_per_day",
            )
        }),
        ("Relations", {
            "fields": ("venue", "service")
        }),
        ("Extra", {
            "fields": ("tags", "is_active")
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at")
        }),
    )


# -------------------- Photos Admin (Optional standalone) --------------------

@admin.register(Photos)
class PhotosAdmin(admin.ModelAdmin):
    list_display = ("id", "content_type", "object_id", "is_primary", "uploaded_at")
    list_filter = ("content_type", "is_primary")
    search_fields = ("object_id",)
    readonly_fields = ("uploaded_at",)
