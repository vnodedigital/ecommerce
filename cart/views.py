from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from django.shortcuts import get_object_or_404
from django.db import transaction
from decimal import Decimal
from .models import Cart, CartItem, SavedItem, Coupon
from .serializers import (
    CartSerializer, CartItemSerializer, AddToCartSerializer,
    UpdateCartItemSerializer, SavedItemSerializer, CouponSerializer,
    ApplyCouponSerializer, CouponValidationSerializer, CartSummarySerializer
)
from .shipping import ShippingCalculator
from products.models import Product, ProductVariant


class CartView(generics.RetrieveAPIView):
    """Get user's cart"""
    serializer_class = CartSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_object(self):
        cart, created = Cart.objects.get_or_create(user=self.request.user)
        return cart


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def add_to_cart(request):
    """Add product to cart"""
    serializer = AddToCartSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    
    user = request.user
    product_id = serializer.validated_data['product_id']
    variant_id = serializer.validated_data.get('variant_id')
    quantity = serializer.validated_data['quantity']
    
    # Get or create cart
    cart, created = Cart.objects.get_or_create(user=user)
    
    # Get product and variant
    product = get_object_or_404(Product, id=product_id, is_active=True)
    variant = None
    if variant_id:
        variant = get_object_or_404(ProductVariant, id=variant_id, is_active=True)
    
    # Check stock availability
    if variant:
        if variant.stock_quantity < quantity:
            return Response({
                'error': f'Only {variant.stock_quantity} items available in stock'
            }, status=status.HTTP_400_BAD_REQUEST)
    else:
        if product.track_inventory and product.stock_quantity < quantity:
            return Response({
                'error': f'Only {product.stock_quantity} items available in stock'
            }, status=status.HTTP_400_BAD_REQUEST)
    
    # Add to cart or update quantity
    cart_item, created = CartItem.objects.get_or_create(
        cart=cart,
        product=product,
        variant=variant,
        defaults={'quantity': quantity}
    )
    
    if not created:
        # Update quantity
        new_quantity = cart_item.quantity + quantity
        
        # Check stock for new quantity
        if variant:
            if variant.stock_quantity < new_quantity:
                return Response({
                    'error': f'Only {variant.stock_quantity} items available in stock'
                }, status=status.HTTP_400_BAD_REQUEST)
        else:
            if product.track_inventory and product.stock_quantity < new_quantity:
                return Response({
                    'error': f'Only {product.stock_quantity} items available in stock'
                }, status=status.HTTP_400_BAD_REQUEST)
        
        cart_item.quantity = new_quantity
        cart_item.save()
    
    return Response({
        'message': 'Product added to cart successfully',
        'cart_item': CartItemSerializer(cart_item, context={'request': request}).data,
        'cart_total': cart.total_items
    })


@api_view(['PUT'])
@permission_classes([permissions.IsAuthenticated])
def update_cart_item(request, item_id):
    """Update cart item quantity"""
    serializer = UpdateCartItemSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    
    quantity = serializer.validated_data['quantity']
    
    # Get cart item
    cart_item = get_object_or_404(
        CartItem, 
        id=item_id, 
        cart__user=request.user
    )
    
    # Check stock availability
    if cart_item.variant:
        if cart_item.variant.stock_quantity < quantity:
            return Response({
                'error': f'Only {cart_item.variant.stock_quantity} items available in stock'
            }, status=status.HTTP_400_BAD_REQUEST)
    else:
        if cart_item.product.track_inventory and cart_item.product.stock_quantity < quantity:
            return Response({
                'error': f'Only {cart_item.product.stock_quantity} items available in stock'
            }, status=status.HTTP_400_BAD_REQUEST)
    
    cart_item.quantity = quantity
    cart_item.save()
    
    return Response({
        'message': 'Cart item updated successfully',
        'cart_item': CartItemSerializer(cart_item, context={'request': request}).data
    })


@api_view(['DELETE'])
@permission_classes([permissions.IsAuthenticated])
def remove_from_cart(request, item_id):
    """Remove item from cart"""
    cart_item = get_object_or_404(
        CartItem, 
        id=item_id, 
        cart__user=request.user
    )
    
    cart_item.delete()
    
    return Response({
        'message': 'Product removed from cart successfully'
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def clear_cart(request):
    """Clear all items from cart"""
    try:
        cart = Cart.objects.get(user=request.user)
        cart.clear()
        return Response({
            'message': 'Cart cleared successfully'
        })
    except Cart.DoesNotExist:
        return Response({
            'message': 'Cart is already empty'
        })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def save_for_later(request, item_id):
    """Move cart item to saved items"""
    cart_item = get_object_or_404(
        CartItem, 
        id=item_id, 
        cart__user=request.user
    )
    
    # Create saved item
    saved_item, created = SavedItem.objects.get_or_create(
        user=request.user,
        product=cart_item.product,
        variant=cart_item.variant,
        defaults={
            'quantity': cart_item.quantity,
            'unit_price': cart_item.unit_price
        }
    )
    
    if not created:
        saved_item.quantity += cart_item.quantity
        saved_item.save()
    
    # Remove from cart
    cart_item.delete()
    
    return Response({
        'message': 'Item saved for later',
        'saved_item': SavedItemSerializer(saved_item, context={'request': request}).data
    })


class SavedItemsView(generics.ListAPIView):
    """List saved items"""
    serializer_class = SavedItemSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return SavedItem.objects.filter(user=self.request.user).select_related('product', 'variant')


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def move_to_cart(request, saved_item_id):
    """Move saved item back to cart"""
    saved_item = get_object_or_404(
        SavedItem, 
        id=saved_item_id, 
        user=request.user
    )
    
    cart_item = saved_item.move_to_cart()
    
    return Response({
        'message': 'Item moved to cart',
        'cart_item': CartItemSerializer(cart_item, context={'request': request}).data
    })


@api_view(['DELETE'])
@permission_classes([permissions.IsAuthenticated])
def remove_saved_item(request, saved_item_id):
    """Remove saved item"""
    saved_item = get_object_or_404(
        SavedItem, 
        id=saved_item_id, 
        user=request.user
    )
    
    saved_item.delete()
    
    return Response({
        'message': 'Saved item removed successfully'
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def apply_coupon(request):
    """Apply coupon to cart"""
    serializer = ApplyCouponSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    
    coupon_code = serializer.validated_data['code']
    user = request.user
    
    # Get cart
    try:
        cart = Cart.objects.get(user=user)
    except Cart.DoesNotExist:
        return Response({
            'error': 'Cart is empty'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    if not cart.items.exists():
        return Response({
            'error': 'Cart is empty'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # Get coupon
    try:
        coupon = Coupon.objects.get(code=coupon_code, is_active=True)
    except Coupon.DoesNotExist:
        return Response({
            'error': 'Invalid coupon code'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # Validate coupon
    cart_total = cart.subtotal
    is_valid, message = coupon.is_valid(user, cart_total)
    
    if not is_valid:
        return Response({
            'error': message
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # Calculate discount
    discount_amount = coupon.calculate_discount(cart_total)
    
    # Store coupon in session (you might want to store this differently)
    request.session['applied_coupon'] = {
        'code': coupon.code,
        'discount_amount': str(discount_amount)
    }
    
    return Response({
        'message': 'Coupon applied successfully',
        'coupon': CouponSerializer(coupon).data,
        'discount_amount': discount_amount
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def remove_coupon(request):
    """Remove applied coupon"""
    if 'applied_coupon' in request.session:
        del request.session['applied_coupon']
    
    return Response({
        'message': 'Coupon removed successfully'
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def cart_summary(request):
    """Get cart summary with totals"""
    try:
        cart = Cart.objects.get(user=request.user)
    except Cart.DoesNotExist:
        return Response({
            'subtotal': '0.00',
            'shipping_cost': '0.00',
            'tax_amount': '0.00',
            'discount_amount': '0.00',
            'coupon_discount': '0.00',
            'total_amount': '0.00',
            'total_items': 0,
            'total_weight': '0.00'
        })
    
    subtotal = cart.subtotal
    shipping_cost = Decimal('0.00')  # Implement shipping calculation
    tax_amount = Decimal('0.00')     # Implement tax calculation
    discount_amount = Decimal('0.00')
    coupon_discount = Decimal('0.00')
    coupon_code = ''
    
    # Get applied coupon from session
    applied_coupon = request.session.get('applied_coupon')
    if applied_coupon:
        coupon_discount = Decimal(applied_coupon['discount_amount'])
        coupon_code = applied_coupon['code']
    
    total_amount = subtotal + shipping_cost + tax_amount - discount_amount - coupon_discount
    
    summary = {
        'subtotal': subtotal,
        'shipping_cost': shipping_cost,
        'tax_amount': tax_amount,
        'discount_amount': discount_amount,
        'coupon_discount': coupon_discount,
        'total_amount': total_amount,
        'coupon_code': coupon_code,
        'total_items': cart.total_items,
        'total_weight': cart.total_weight or Decimal('0.00')
    }
    
    return Response(summary)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_shipping_options(request):
    """Get available shipping options for user's cart"""
    location = request.GET.get('location', 'dhaka').lower()
    
    if location not in ['dhaka', 'outside']:
        return Response({
            'error': 'Invalid location. Must be "dhaka" or "outside"'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # Get user's cart
    try:
        cart = Cart.objects.get(user=request.user)
        cart_items = cart.items.select_related('product').all()
        
        if not cart_items:
            return Response({
                'error': 'Cart is empty'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Calculate shipping options
        shipping_calculator = ShippingCalculator(cart_items, location)
        shipping_summary = shipping_calculator.get_shipping_summary()
        
        return Response(shipping_summary)
        
    except Cart.DoesNotExist:
        return Response({
            'error': 'Cart not found'
        }, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def calculate_shipping_cost(request):
    """Calculate shipping cost for specific option and location"""
    shipping_type = request.data.get('shipping_type')
    location = request.data.get('location', 'dhaka').lower()
    
    if not shipping_type:
        return Response({
            'error': 'shipping_type is required'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    if location not in ['dhaka', 'outside']:
        return Response({
            'error': 'Invalid location. Must be "dhaka" or "outside"'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    if shipping_type not in ['free', 'standard', 'express']:
        return Response({
            'error': 'Invalid shipping_type. Must be "free", "standard", or "express"'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        cart = Cart.objects.get(user=request.user)
        cart_items = cart.items.select_related('product').all()
        
        if not cart_items:
            return Response({
                'error': 'Cart is empty'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Calculate shipping cost
        shipping_calculator = ShippingCalculator(cart_items, location)
        cost = shipping_calculator.calculate_shipping_cost(shipping_type)
        
        if cost is None:
            return Response({
                'error': f'{shipping_type} shipping not available for {location}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        return Response({
            'shipping_type': shipping_type,
            'location': location,
            'cost': cost,
            'currency': '৳'
        })
        
    except Cart.DoesNotExist:
        return Response({
            'error': 'Cart not found'
        }, status=status.HTTP_404_NOT_FOUND)
