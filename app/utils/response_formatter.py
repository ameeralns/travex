import logging

logger = logging.getLogger(__name__)

def get_place_type_emoji(place_type):
    """Get appropriate emoji for different place types"""
    type_lower = place_type.lower() if place_type else ""
    emoji_map = {
        'restaurant': '🍽️',
        'cafe': '☕',
        'coffee': '☕',
        'bar': '🍸',
        'club': '🎉',
        'nightclub': '🎉',
        'park': '🌳',
        'trail': '🥾',
        'school': '🎓',
        'university': '🎓',
        'law': '⚖️',
        'financial': '💰',
        'bank': '🏦',
        'gym': '💪',
        'shopping': '🛍️',
        'mall': '🏬',
        'hospital': '🏥',
        'clinic': '🏥',
        'library': '📚',
        'museum': '🏛️',
        'theater': '🎭',
        'cinema': '🎬',
        'hotel': '🏨',
        'default': '📍'
    }
    
    for key, emoji in emoji_map.items():
        if key in type_lower:
            return emoji
    return emoji_map['default']

def format_place_for_sms(place):
    """Format place details for SMS"""
    if not place:
        return "Sorry, couldn't find exactly what you're looking for! Try another search!"
    
    # Build a concise SMS response
    response = [
        f"🌟 {place.metadata.get('name', 'Unnamed Place')}",
        f"📍 {place.metadata.get('address', 'Address not available')}",
    ]
    
    # Add rating if available
    if 'rating' in place.metadata:
        response.append(f"⭐ {place.metadata['rating']} stars")
    
    # Add price level if available
    if 'price_level' in place.metadata:
        response.append(f"💰 {'$' * int(place.metadata['price_level'])}")
    
    # Add phone if available
    if 'phone' in place.metadata:
        response.append(f"📞 {place.metadata['phone']}")
    
    # Add website if available
    if 'website' in place.metadata:
        response.append(f"🌐 {place.metadata['website']}")
    
    return "\n".join(response)

def format_place_for_voice(place):
    """Format place details for voice response"""
    if not place:
        return "Sorry, I couldn't find exactly what you're looking for. Try another search!"
    
    # Extract place details
    name = place.metadata.get('name', 'this place')
    rating = place.metadata.get('rating', 'N/A')
    price = place.metadata.get('price_level', 'N/A')
    
    # Create a short, energetic response
    response = f"Found an amazing spot! {name}! "
    
    if rating != 'N/A':
        response += f"It's got {rating} stars! "
    
    if 'address' in place.metadata:
        response += f"You'll find it at {place.metadata['address']}! "
    
    response += "Check your phone for all the details!"
    
    return response 