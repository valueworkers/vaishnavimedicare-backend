from django.contrib import admin
from .models import FAQTopic, FAQItem


class FAQItemInline(admin.TabularInline):
    model = FAQItem
    extra = 1
    fields = ("question", "answer", "created_at", "updated_at")
    readonly_fields = ("created_at", "updated_at")


@admin.register(FAQTopic)
class FAQTopicAdmin(admin.ModelAdmin):
    list_display = ("id", "topic", "created_at", "updated_at")
    search_fields = ("topic",)
    list_filter = ("created_at",)
    ordering = ("-created_at",)
    inlines = [FAQItemInline]


@admin.register(FAQItem)
class FAQItemAdmin(admin.ModelAdmin):
    list_display = ("id", "short_question", "topic", "created_at")
    search_fields = ("question", "answer", "topic__topic")
    list_filter = ("topic", "created_at")
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "updated_at")

    def short_question(self, obj):
        return obj.question[:50]
    short_question.short_description = "Question"