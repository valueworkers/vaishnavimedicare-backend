
from django_filters import rest_framework as filters
from django.db.models import Q


class EntityFilter(filters.FilterSet):
    """
    One filter class for Venue, Service, Resource.
    It automatically checks which fields exist on the model.
    """

    # Common filters
    search = filters.CharFilter(method="filter_search")
    service_type = filters.CharFilter(field_name="service_type", lookup_expr="iexact")  
    city = filters.CharFilter(field_name="city", lookup_expr="iexact")
    owner = filters.NumberFilter(field_name="owner__id")
    manager = filters.NumberFilter(method="filter_manager")
    staff = filters.NumberFilter(method="filter_staff")
    
    # GenericRelation flags
    has_photos = filters.BooleanFilter(method="filter_has_photos")
    has_logo = filters.BooleanFilter(method="filter_has_logo")

    # Tags (JSON list)
    tags = filters.CharFilter(method="filter_tags")

    # Price filters (Service + Venue + Resource)
    min_price = filters.NumberFilter(method="filter_min_price")
    max_price = filters.NumberFilter(method="filter_max_price")

    # Resource quantity filters
    min_quantity = filters.NumberFilter(method="filter_min_quantity")
    max_quantity = filters.NumberFilter(method="filter_max_quantity")

    # Venue capacity filters
    min_capacity = filters.NumberFilter(method="filter_min_capacity")
    max_capacity = filters.NumberFilter(method="filter_max_capacity")
    
    class Meta:
        fields = []
    

    # -------------------- Search --------------------
    def filter_search(self, queryset, name, value):
        qs = queryset
        if hasattr(qs.model, "name"):
            qs = qs.filter(Q(name__icontains=value) | Q(description__icontains=value))
        return qs

    # -------------------- Tags --------------------
    def filter_tags(self, queryset, name, value):
        if hasattr(queryset.model, "tags"):
            return queryset.filter(tags__contains=[value])
        return queryset

    # -------------------- Manager --------------------
    def filter_manager(self, queryset, name, value):
        if hasattr(queryset.model, "manager"):
            return queryset.filter(manager__id=value)
        return queryset.none()

    # -------------------- Staff --------------------
    def filter_staff(self, queryset, name, value):
        if hasattr(queryset.model, "staff"):
            return queryset.filter(staff__id=value)
        return queryset.none()

    # -------------------- Photos --------------------
    def filter_has_photos(self, queryset, name, value):
        if not value:
            return queryset
        
        # Works for Venue, Service, Resource
        return queryset.filter(photos__isnull=False).distinct()

    # -------------------- Logo --------------------
    def filter_has_logo(self, queryset, name, value):
        if not value:
            return queryset
        
        if hasattr(queryset.model, "logo"):
            return queryset.exclude(logo="").exclude(logo=None)
        return queryset

    # -------------------- Price (Service + Venue + Resource) --------------------
    def filter_min_price(self, queryset, name, value):
        model = queryset.model
        
        if hasattr(model, "quick_info"):  # Service
            return queryset.filter(quick_info__starting_price__gte=value)

        if hasattr(model, "price_per_event"):  # Venue
            return queryset.filter(price_per_event__gte=value)

        if hasattr(model, "sell_price_per_unit"):  # Resource
            return queryset.filter(sell_price_per_unit__gte=value)

        return queryset

    def filter_max_price(self, queryset, name, value):
        model = queryset.model
        
        if hasattr(model, "quick_info"):
            return queryset.filter(quick_info__starting_price__lte=value)

        if hasattr(model, "price_per_event"):
            return queryset.filter(price_per_event__lte=value)

        if hasattr(model, "sell_price_per_unit"):
            return queryset.filter(sell_price_per_unit__lte=value)

        return queryset

    # -------------------- Resource Quantity --------------------
    def filter_min_quantity(self, queryset, name, value):
        if hasattr(queryset.model, "available_quantity"):
            return queryset.filter(available_quantity__gte=value)
        return queryset

    def filter_max_quantity(self, queryset, name, value):
        if hasattr(queryset.model, "available_quantity"):
            return queryset.filter(available_quantity__lte=value)
        return queryset

    # -------------------- Venue Capacity --------------------
    def filter_min_capacity(self, queryset, name, value):
        if hasattr(queryset.model, "capacity"):
            return queryset.filter(capacity__gte=value)
        return queryset

    def filter_max_capacity(self, queryset, name, value):
        if hasattr(queryset.model, "capacity"):
            return queryset.filter(capacity__lte=value)
        return queryset
