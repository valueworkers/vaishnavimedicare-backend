from rest_framework import serializers
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from .models import *
from accounts.models import CustomUser

# --------- PHOTO SERIALIZER -----------------------------------------------
class PhotosSerializer(serializers.ModelSerializer):
    class Meta:
        model = Photos
        fields = "__all__"
        read_only_fields = ["id", "uploaded_at"]

class UserMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ["id", "first_name", "last_name", "email", "mobile_number", "user_type"]

class LocationMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Location
        fields = [
            "building_name",
            "address_line1",
            "address_line2",
            "locality",
            "city",
            "state",
            "postal_code",
            "location_type"
        ]

# --------- VENUE SERIALIZER -----------------------------------------------
class VenueSerializer(serializers.ModelSerializer):
    photos = PhotosSerializer(many=True, read_only=True)
    owner = UserMiniSerializer(read_only=True)
    manager = UserMiniSerializer(many=True, read_only=True)
    staff = UserMiniSerializer(many=True, read_only=True)

    # Write-only flat fields (input)
    location_type = serializers.CharField(write_only=True)
    building_name = serializers.CharField(write_only=True)
    address_line1 = serializers.CharField(write_only=True)
    address_line2 = serializers.CharField(write_only=True, required=False, allow_blank=True)
    locality = serializers.CharField(write_only=True, required=False, allow_blank=True)
    city = serializers.CharField(write_only=True)
    state = serializers.CharField(write_only=True)
    postal_code = serializers.CharField(write_only=True)

    # Read-only nested output
    location = LocationMiniSerializer(read_only=True)

    class Meta:
        model = Venue
        fields = [
            "id", "owner", "manager", "staff",
            "name", "description",

            "location_type",
            "building_name",
            "address_line1",
            "address_line2",
            "locality",
            "city",
            "state",
            "postal_code",

            "location",   # output only

            "capacity", "price_per_event", "rooms", "floors",
            "parking_slots", "external_decorators_allow",
            "external_caterers_allow", "amenities",
            "seating_arrangement",
            "is_active", "is_deleted",
            "created_at", "updated_at",
            "photos", "logo"
        ]
        read_only_fields = ["is_deleted", "created_at", "updated_at"]


    # --------------------------------------------------------
    # CREATE
    # --------------------------------------------------------
    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]

        photos_data = request.FILES.getlist("photos")
        logo = request.FILES.get("logo")

        # Extract flat location fields
        location_data = {
            "building_name": validated_data.pop("building_name"),
            "address_line1": validated_data.pop("address_line1"),
            "address_line2": validated_data.pop("address_line2", ""),
            "locality": validated_data.pop("locality", ""),
            "city": validated_data.pop("city"),
            "state": validated_data.pop("state"),
            "postal_code": validated_data.pop("postal_code"),
            "location_type": validated_data.pop("location_type"),
            "user": request.user,
        }

        # Create location
        location = Location.objects.create(**location_data)

        # Create venue
        venue = Venue.objects.create(
            **validated_data,
            location=location,
            logo=logo
        )

        # Save photos
        if photos_data:
            ct = ContentType.objects.get_for_model(Venue)
            Photos.objects.bulk_create([
                Photos(
                    image=image,
                    is_primary=False,
                    content_type=ct,
                    object_id=venue.id,
                )
                for image in photos_data
            ])

        return venue

    # --------------------------------------------------------
    # UPDATE
    # --------------------------------------------------------
    @transaction.atomic
    def update(self, instance, validated_data):
        request = self.context["request"]

        photos_data = request.FILES.getlist("photos")
        logo = request.FILES.get("logo")

        # Update location fields
        location_fields = ["location_type","building_name", "address_line1", "address_line2", "locality", "city", "state", "postal_code"]

        for field in location_fields:
            if field in validated_data:
                setattr(instance.location, field, validated_data.pop(field))

        instance.location.save()

        # Update venue fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if logo:
            instance.logo = logo

        instance.save()

        # Add new photos
        if photos_data:
            ct = ContentType.objects.get_for_model(Venue)
            Photos.objects.bulk_create([
                Photos(
                    image=image,
                    is_primary=False,
                    content_type=ct,
                    object_id=instance.id,
                )
                for image in photos_data
            ])

        return instance

class VenueDropdownSerializer(serializers.ModelSerializer):
    locality = serializers.CharField(read_only=True,source='location.locality')

    class Meta:
        model = Venue
        fields = [
            "id", 
            "name",
            "locality",
        ]

# --------- SERVICE SERIALIZER ---------------------------------------------
class ServiceSerializer(serializers.ModelSerializer):
    photos = PhotosSerializer(many=True, read_only=True)
    owner = UserMiniSerializer(read_only=True)
    manager = UserMiniSerializer(many=True, read_only=True)
    staff = UserMiniSerializer(many=True, read_only=True)

    class Meta:
        model = Service
        fields = [
            "id", "owner", "manager", "staff", "venue",
            "name", "description", "address","city",
            "contact","website","service_type", "tags", "quick_info",
            "is_active", "is_deleted",
            "created_at", "updated_at",
            "photos","logo"
        ]
        read_only_fields = ["created_at", "updated_at"]

    # --------------------------------------------------------
    # CREATE SERVICE WITH PHOTOS
    # --------------------------------------------------------
    def create(self, validated_data):
        photos_data = self.context["request"].FILES.getlist("photos")
        validated_data["logo"] = self.context["request"].FILES.get("logo")
        venues = validated_data.pop("venue",None)
            
        service = Service.objects.create(**validated_data)
        
        if venues:
            service.venue.set(venues)

        if photos_data:
            ct = ContentType.objects.get_for_model(Service)
            photo_objs = [
                Photos(
                    image=image,
                    is_primary=False,
                    content_type=ct,
                    object_id=service.id,
                )
                for image in photos_data
            ]
            Photos.objects.bulk_create(photo_objs)

        return service

    # --------------------------------------------------------
    # UPDATE SERVICE + OPTIONAL PHOTO UPDATE
    # --------------------------------------------------------
    def update(self, instance, validated_data):
        request = self.context["request"]

        photos_data = request.FILES.getlist("photos")
        logo = request.FILES.get("logo")

        if logo:
            validated_data["logo"] = logo

        venues = validated_data.pop("venue", None)

        # Update normal fields
        instance = super().update(instance, validated_data)

        # Update ManyToMany
        if venues is not None:
            instance.venue.set(venues)

        # Replace Photos (NOT add)
        if photos_data:
            from django.contrib.contenttypes.models import ContentType

            ct = ContentType.objects.get_for_model(Service)

            # 🔥 Delete old photos first
            Photos.objects.filter(
                content_type=ct,
                object_id=instance.id
            ).delete()

            # Create new ones
            photo_objs = [
                Photos(
                    image=image,
                    is_primary=False,
                    content_type=ct,
                    object_id=instance.id,
                )
                for image in photos_data
            ]

            Photos.objects.bulk_create(photo_objs)

        return instance

class ServiceDropdownSerializer(serializers.ModelSerializer):
    venue = VenueDropdownSerializer(many=True,read_only=True)
    class Meta:
        model = Venue
        fields = [
            "id", 
            "name",
            "venue",
        ]