from rest_framework import serializers
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from .models import User, UserProfile, Address


class UserRegistrationSerializer(serializers.ModelSerializer):
    """User registration serializer"""
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True)
    
    class Meta:
        model = User
        fields = (
            'username', 'email', 'password', 'password_confirm',
            'first_name', 'last_name', 'phone'
        )
    
    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError("Passwords don't match.")
        return attrs
    
    def create(self, validated_data):
        validated_data.pop('password_confirm')
        user = User.objects.create_user(**validated_data)
        # Create user profile
        UserProfile.objects.create(user=user)
        return user


class UserLoginSerializer(serializers.Serializer):
    """User login serializer"""
    email = serializers.EmailField()
    password = serializers.CharField()
    
    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')
        
        if email and password:
            user = authenticate(username=email, password=password)
            if not user:
                raise serializers.ValidationError('Invalid credentials.')
            if not user.is_active:
                raise serializers.ValidationError('User account is disabled.')
            attrs['user'] = user
        else:
            raise serializers.ValidationError('Must include email and password.')
        
        return attrs


class UserProfileSerializer(serializers.ModelSerializer):
    """User profile serializer"""
    class Meta:
        model = UserProfile
        fields = (
            'newsletter_subscription', 'email_notifications', 'sms_notifications',
            'preferred_currency', 'preferred_language'
        )


class AddressSerializer(serializers.ModelSerializer):
    """Address serializer"""
    full_address = serializers.ReadOnlyField()
    
    class Meta:
        model = Address
        fields = (
            'id', 'address_type', 'address_line_1', 'address_line_2',
            'city', 'state', 'postal_code', 'country', 'is_default',
            'full_address', 'created_at'
        )
        read_only_fields = ('id', 'created_at')
    
    def validate(self, attrs):
        # Ensure only one default address per type per user
        if attrs.get('is_default'):
            user = self.context['request'].user
            address_type = attrs.get('address_type')
            
            existing_default = Address.objects.filter(
                user=user, 
                address_type=address_type, 
                is_default=True
            ).exclude(pk=self.instance.pk if self.instance else None)
            
            if existing_default.exists():
                existing_default.update(is_default=False)
        
        return attrs


class UserSerializer(serializers.ModelSerializer):
    """User serializer for profile management"""
    profile = UserProfileSerializer(read_only=True)
    addresses = AddressSerializer(many=True, read_only=True)
    full_address = serializers.ReadOnlyField()
    
    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'first_name', 'last_name',
            'phone', 'date_of_birth', 'profile_picture',
            'address_line_1', 'address_line_2', 'city', 'state',
            'postal_code', 'country', 'full_address',
            'profile', 'addresses', 'date_joined'
        )
        read_only_fields = ('id', 'username', 'date_joined')


class UserUpdateSerializer(serializers.ModelSerializer):
    """User update serializer"""
    profile = UserProfileSerializer(required=False)
    
    class Meta:
        model = User
        fields = (
            'first_name', 'last_name', 'phone', 'date_of_birth',
            'profile_picture', 'address_line_1', 'address_line_2',
            'city', 'state', 'postal_code', 'country', 'profile'
        )
    
    def update(self, instance, validated_data):
        profile_data = validated_data.pop('profile', None)
        
        # Update user fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # Update profile fields
        if profile_data:
            profile, created = UserProfile.objects.get_or_create(user=instance)
            for attr, value in profile_data.items():
                setattr(profile, attr, value)
            profile.save()
        
        return instance


class ChangePasswordSerializer(serializers.Serializer):
    """Change password serializer"""
    old_password = serializers.CharField()
    new_password = serializers.CharField(validators=[validate_password])
    new_password_confirm = serializers.CharField()
    
    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError("New passwords don't match.")
        return attrs
    
    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError("Old password is incorrect.")
        return value
