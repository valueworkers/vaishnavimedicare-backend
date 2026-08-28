from rest_framework import serializers
from .models import FAQTopic, FAQItem
from rest_framework import serializers
from .models import Video

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