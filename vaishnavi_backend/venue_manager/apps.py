from django.apps import AppConfig


class VenueManagerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'venue_manager'
    def ready(self):
        import venue_manager.signals
