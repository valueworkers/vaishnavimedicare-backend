from django.contrib.auth.backends import ModelBackend
from django.db.models import Q
from .models import CustomUser

class EmailMobileAuthBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
            
        try:
            user = CustomUser.objects.filter(
                Q(email=username) | Q(mobile_number=username)
            ).first()

            if user and all((
                user.check_password(password),
                self.user_can_authenticate(user))
            ):return user
                            
        except CustomUser.DoesNotExist:
            return None
        return None
    
    def get_user(self, user_id):
        try:
            user = CustomUser.objects.get(pk=user_id)
            return user if self.user_can_authenticate(user) else None
        except CustomUser.DoesNotExist:
            return None