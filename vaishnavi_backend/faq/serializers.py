from rest_framework import serializers
from .models import FAQTopic, FAQItem, Video, Contact


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = [
            "id",
            "display_name",
            "mobile_number",
            "email",
            "platform",
            "url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, attrs):
        # require at least one contact method
        mobile = attrs.get("mobile_number", getattr(self.instance, "mobile_number", None))
        email = attrs.get("email", getattr(self.instance, "email", None))
        url = attrs.get("url", getattr(self.instance, "url", None))

        if not any([mobile, email, url]):
            raise serializers.ValidationError(
                "At least one of mobile_number, email, or url must be provided."
            )
        return attrs
    
class VideoSerializer(serializers.ModelSerializer):
    
    class Meta:
        model = Video
        fields = "__all__"

class FAQItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = FAQItem
        fields = ["id", "question", "answer", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

class FAQTopicSerializer(serializers.ModelSerializer):
    qanda = FAQItemSerializer(many=True)

    class Meta:
        model = FAQTopic
        fields = ["id", "topic", "qanda", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def create(self, validated_data):
        qanda_data = validated_data.pop("qanda", [])
        topic = FAQTopic.objects.create(**validated_data)

        for item in qanda_data:
            FAQItem.objects.create(topic=topic, **item)

        return topic

    def update(self, instance, validated_data):
        qanda_data = validated_data.pop("qanda", None)

        instance.topic = validated_data.get("topic", instance.topic)
        instance.save()

        if qanda_data is not None:
            instance.qanda.all().delete()
            for item in qanda_data:
                FAQItem.objects.create(topic=instance, **item)

        return instance