from openai import OpenAI
import os
import json
import logging
from app import get_openai_client

logger = logging.getLogger(__name__)
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

def analyze_query_intent(query, conversation_context=None):
    """
    Analyzes user query to determine intent and extract relevant information
    Returns a structured analysis of the query intent
    """
    try:
        query_lower = query.lower().strip()
        
        # Reference detection patterns
        reference_patterns = [
            'first one', 'second one', 'third one', 'last one',
            'tell me more', 'more about', 'what about',
            'can you tell me about', 'first place', 'that one'
        ]
        
        # Check for references to previous results first
        if conversation_context and conversation_context.current_results:
            if any(pattern in query_lower for pattern in reference_patterns):
                return {
                    'query_type': 'REFERENCE',
                    'requires_search': False,
                    'should_maintain_context': True,
                    'confidence': 0.95,
                    'suggested_action': 'provide_details'
                }

        # Quick checks for common patterns
        is_greeting = any(word in query_lower for word in ['hi', 'hello', 'hey', 'greetings'])
        is_farewell = any(word in query_lower for word in ['bye', 'goodbye', 'thank', 'thanks'])
        is_affirmative = query_lower in ['yes', 'yeah', 'sure', 'okay', 'yep', 'yup']
        is_negative = query_lower in ['no', 'nope', 'nah', 'not']
        
        # Handle greetings
        if is_greeting and len(query_lower.split()) <= 3:
            return {
                'query_type': 'INITIAL_GREETING',
                'requires_search': False,
                'should_maintain_context': False,
                'confidence': 0.95,
                'suggested_action': 'ask_for_city'
            }
            
        # Handle farewells
        if is_farewell:
            return {
                'query_type': 'FAREWELL',
                'requires_search': False,
                'should_maintain_context': False,
                'confidence': 0.95,
                'suggested_action': 'say_goodbye'
            }
            
        # Handle context-dependent affirmative responses
        if is_affirmative and conversation_context:
            if conversation_context.current_place:
                return {
                    'query_type': 'MORE_INFO',
                    'requires_search': False,
                    'should_maintain_context': True,
                    'confidence': 0.9,
                    'suggested_action': 'provide_details',
                    'place_id': conversation_context.current_place.get('id')
                }
            elif conversation_context.remaining_results:
                return {
                    'query_type': 'FOLLOW_UP',
                    'requires_search': False,
                    'should_maintain_context': True,
                    'confidence': 0.9,
                    'suggested_action': 'show_more_results'
                }
                
        # Handle negative responses
        if is_negative and conversation_context:
            return {
                'query_type': 'PREFERENCE',
                'requires_search': True,
                'should_maintain_context': False,
                'confidence': 0.8,
                'suggested_action': 'new_search'
            }
            
        # Extract location information
        location_info = extract_location(query)
        
        # Detect if this is a follow-up question
        is_follow_up = False
        if conversation_context:
            follow_up_indicators = [
                'what about',
                'how about',
                'tell me more',
                'can you',
                'what is',
                'where is',
                'when is',
                'is it',
                'do they',
                'more',
                'another',
                'different',
                'instead'
            ]
            is_follow_up = any(indicator in query_lower for indicator in follow_up_indicators)
            
        # Determine if this is a conversation or search
        conversation_indicators = [
            'what do you think',
            'can you recommend',
            'suggest',
            'help me find',
            'looking for',
            'where can i',
            'tell me about'
        ]
        
        is_conversation = any(indicator in query_lower for indicator in conversation_indicators)
        
        # Build the response
        response = {
            'query_type': 'PLACE_SEARCH' if not is_conversation else 'CONVERSATION',
            'requires_search': True,
            'should_maintain_context': is_follow_up,
            'is_follow_up': is_follow_up,
            'confidence': 0.8,
            'extracted_location': location_info,
            'suggested_action': 'perform_search'
        }
        
        # Add any detected preferences
        preferences = {}
        
        # Price preferences
        if any(word in query_lower for word in ['cheap', 'affordable', 'budget', 'inexpensive']):
            preferences['price_level'] = 'budget'
        elif any(word in query_lower for word in ['expensive', 'fancy', 'high-end', 'upscale']):
            preferences['price_level'] = 'upscale'
        elif any(word in query_lower for word in ['moderate', 'reasonable', 'mid-range']):
            preferences['price_level'] = 'moderate'
            
        # Atmosphere preferences
        atmosphere = []
        if 'romantic' in query_lower or 'date' in query_lower:
            atmosphere.append('romantic')
        if 'quiet' in query_lower or 'peaceful' in query_lower:
            atmosphere.append('quiet')
        if 'casual' in query_lower or 'relaxed' in query_lower:
            atmosphere.append('casual')
        if 'outdoor' in query_lower or 'patio' in query_lower:
            atmosphere.append('outdoor')
        if atmosphere:
            preferences['atmosphere'] = atmosphere
            
        if preferences:
            response['extracted_preferences'] = preferences
            
        return response
        
    except Exception as e:
        logger.error(f"Error analyzing query intent: {str(e)}")
        return {
            'query_type': 'PLACE_SEARCH',
            'requires_search': True,
            'should_maintain_context': False,
            'confidence': 0.5,
            'suggested_action': 'perform_search'
        }
        
def extract_location(query):
    """Helper function to extract location information from query"""
    location_info = {}
    query_lower = query.lower()
    
    # Common city names (expand this list as needed)
    cities = ['new york', 'los angeles', 'chicago', 'houston', 'phoenix', 'philadelphia',
              'san antonio', 'san diego', 'dallas', 'san jose', 'austin', 'jacksonville',
              'fort worth', 'columbus', 'san francisco', 'charlotte', 'indianapolis',
              'seattle', 'denver', 'boston']
              
    # Check for "in {city}" pattern
    for city in cities:
        if f"in {city}" in query_lower or f"in the {city}" in query_lower:
            location_info['city'] = city.title()
            break
            
    # If not found, check for direct city mentions
    if not location_info:
        for city in cities:
            if city in query_lower:
                location_info['city'] = city.title()
                break
    
    # Add state information if available (focusing on Texas for now)
    if location_info.get('city'):
        location_info['state'] = 'Texas'
    
    return location_info

def generate_direct_response(query, conversation_context):
    """Generate a direct AI response for general questions without requiring search"""
    try:
        messages = [
            {
                "role": "system",
                "content": f"""You are a knowledgeable local guide for {conversation_context.current_city if conversation_context else 'the city'}.
                Answer questions naturally and conversationally about the city, culture, weather, events, etc.
                If you're not confident about specific current information, be honest and suggest checking official sources.
                
                Current context:
                - City: {conversation_context.current_city if conversation_context else 'Unknown'}
                - Topic: {conversation_context.current_topic if conversation_context else 'General'}
                
                Keep responses helpful but concise. If the user should be searching for places instead,
                indicate that in your response."""
            },
            {
                "role": "user",
                "content": query
            }
        ]
        
        response = client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=messages,
            max_tokens=150,
            temperature=0.7
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        logger.error(f"Error generating direct response: {str(e)}")
        return "I apologize, but I'm having trouble understanding. Could you rephrase your question?"

def process_user_query(query, conversation_context=None):
    """Enhanced query processing with intelligent routing"""
    try:
        query_lower = query.lower()
        
        # Extract location information with priority
        location = extract_location(query)
        if not location and conversation_context and conversation_context.current_city:
            location = {'city': conversation_context.current_city}
            
        # Enhanced place type detection
        place_types = {
            'outdoor': ['trail', 'park', 'hiking', 'garden', 'nature', 'outdoor', 'playground'],
            'restaurant': ['restaurant', 'food', 'eat', 'dining', 'cuisine'],
            'bar': ['bar', 'pub', 'drink', 'club', 'lounge'],
            'shopping': ['shop', 'store', 'mall', 'market'],
            'activity': ['activity', 'attraction', 'entertainment'],
            'hotel': ['hotel', 'motel', 'stay', 'accommodation']
        }
        
        # Check for family/kid-friendly indicators
        family_indicators = ['kid', 'kids', 'child', 'children', 'family', 'families']
        has_family_context = any(indicator in query_lower for indicator in family_indicators)
        
        # Detect place type with better context
        detected_place_type = None
        for type_key, type_words in place_types.items():
            if any(word in query_lower for word in type_words):
                detected_place_type = type_key
                break
                
        # If no place type detected but we have context, use it
        if not detected_place_type and conversation_context:
            detected_place_type = conversation_context.get_current_category()
        
        # Extract preferences
        preferences = {}
        if has_family_context:
            preferences['features'] = ['family-friendly', 'kid-friendly']
            preferences['safety'] = 'high'
            preferences['accessibility'] = 'easy'
            
        # Price preferences
        if any(word in query_lower for word in ['cheap', 'affordable', 'budget']):
            preferences['price_level'] = 'budget'
        elif any(word in query_lower for word in ['expensive', 'luxury', 'high-end']):
            preferences['price_level'] = 'upscale'
        
        # Build the final query info
        query_info = {
            'query_text': query,
            'location': location,
            'place_type': detected_place_type or 'place',
            'preferences': preferences,
            'context': {
                'is_rejection': 'no' in query_lower.split() or 'not' in query_lower.split(),
                'wants_alternatives': any(word in query_lower for word in ['else', 'other', 'another', 'different']),
                'specific_aspect': None,
                'reference_to_previous': False,
                'action_type': 'continue_current' if detected_place_type else 'new_search'
            }
        }
        
        # Add search refinements
        if 'price' in query_lower or 'expensive' in query_lower or 'cheap' in query_lower:
            query_info['context']['specific_aspect'] = 'price'
        elif 'location' in query_lower or 'where' in query_lower:
            query_info['context']['specific_aspect'] = 'location'
        elif 'open' in query_lower or 'hours' in query_lower:
            query_info['context']['specific_aspect'] = 'hours'
        
        # Log the processed query info
        logger.info(f"Processed query info: {json.dumps(query_info, indent=2)}")
        
        return query_info
        
    except Exception as e:
        logger.error(f"Error processing query: {str(e)}")
        return {
            'query_text': query,
            'location': {},
            'place_type': 'place',
            'preferences': {},
            'context': {
                'is_rejection': False,
                'wants_alternatives': False,
                'specific_aspect': None,
                'reference_to_previous': False,
                'action_type': 'new_search'
            }
        }

def generate_response(query, places, conversation_context):
    """Generate natural conversational response using OpenAI"""
    try:
        # Prepare context for OpenAI
        places_context = []
        current_category = conversation_context.get_current_category() if conversation_context else None
        
        for place in places[:3]:  # Limit to top 3 places
            places_context.append({
                "name": place.metadata.get('title'),
                "category": place.metadata.get('category', current_category),
                "rating": place.metadata.get('rating'),
                "price_level": place.metadata.get('price_level'),
                "features": place.metadata.get('features'),
                "address": place.metadata.get('address')
            })
            
        messages = [
            {
                "role": "system",
                "content": f"""
                You are a friendly local guide. Generate VERY concise responses about places.
                Current category being discussed: {current_category or 'general places'}
                Keep responses under 100 words. Focus on key details only.
                Format:
                1. Quick intro (1 sentence)
                2. Top place highlight (1-2 sentences per place)
                3. Brief follow-up prompt
                
                Important:
                - Maintain focus on the current category ({current_category or 'general places'})
                - Don't switch to different types of places unless explicitly requested
                - Use category-appropriate language and details
                - Suggest relevant follow-up questions for the current category
                
                Avoid:
                - Unnecessary details or lengthy descriptions
                - Mixing different categories of places
                - Generic responses that don't match the category
                """
            },
            {
                "role": "user",
                "content": f"""
                User query: {query}
                Places: {json.dumps(places_context)}
                Current city: {conversation_context.current_city if conversation_context else None}
                Current category: {current_category or 'general places'}
                """
            }
        ]
        
        response = client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=messages,
            max_tokens=150,
            temperature=0.7
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        logger.error(f"Error generating response: {str(e)}")
        category_default_responses = {
            'hotel': "I found some great hotels nearby. Would you like to hear about them?",
            'restaurant': "I found some great restaurants nearby. Would you like to hear about them?",
            'activity': "I found some interesting activities nearby. Would you like to hear about them?",
            'bar': "I found some nice bars nearby. Would you like to hear about them?",
            'shopping': "I found some good shopping spots nearby. Would you like to hear about them?"
        }
        return category_default_responses.get(current_category, "I found some great places nearby. Would you like to hear about them?")

def handle_aspect_query(aspect, place, conversation_context):
    """Generate response for specific aspect queries using OpenAI"""
    try:
        messages = [
            {
                "role": "system",
                "content": """
                You are a knowledgeable local guide. Generate natural responses about specific aspects of places.
                Be informative but conversational. Suggest relevant follow-up questions.
                If information is missing, offer helpful alternatives.
                """
            },
            {
                "role": "user",
                "content": f"""
                Aspect: {aspect}
                Place details: {json.dumps(place)}
                User preferences: {json.dumps(conversation_context.user_preferences)}
                
                Generate a natural response about this aspect of the place.
                """
            }
        ]
        
        response = client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=messages,
            max_tokens=150,
            temperature=0.7
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        logger.error(f"Error handling aspect query: {str(e)}")
        return f"Let me tell you about the {aspect} of this place."

def create_fallback_query(query_text):
    """Create a basic query when parsing fails"""
    # Extract potential city names from query (basic)
    words = query_text.lower().split()
    common_cities = {'austin', 'houston', 'dallas', 'san antonio', 'fort worth'}
    
    city = next((word for word in words if word in common_cities), '')
    
    return {
        'query_text': query_text,
        'processed_query': query_text,
        'location': {'city': city, 'state': 'texas' if city else '', 'area': ''},
        'place_type': '',
        'sub_type': '',
        'requirements': {}
    } 