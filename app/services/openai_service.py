from openai import OpenAI
import os
import json
import logging
from app import get_openai_client

logger = logging.getLogger(__name__)
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

def process_user_query(query, conversation_context=None):
    """Process user query to extract search intents and understand context"""
    try:
        # First, determine the type of query and appropriate action
        query_lower = query.lower().strip()
        
        # Handle affirmative responses with more context
        if query_lower in ['yes', 'yeah', 'sure', 'okay', 'yep', 'yup']:
            if conversation_context:
                if conversation_context.current_place:
                    # User wants more details about current place
                    return {
                        "query_text": query,
                        "location": {"city": conversation_context.current_city} if conversation_context.current_city else {},
                        "place_type": "restaurant",
                        "preferences": conversation_context.user_preferences,
                        "context": {
                            "is_rejection": False,
                            "wants_alternatives": False,
                            "specific_aspect": "more_details",
                            "reference_to_previous": True,
                            "action_type": "get_place_details"
                        }
                    }
                elif conversation_context.remaining_results:
                    # User wants to hear more results
                    return {
                        "query_text": query,
                        "location": {"city": conversation_context.current_city} if conversation_context.current_city else {},
                        "place_type": "restaurant",
                        "preferences": conversation_context.user_preferences,
                        "context": {
                            "is_rejection": False,
                            "wants_alternatives": True,
                            "specific_aspect": None,
                            "reference_to_previous": False,
                            "action_type": "get_more_results"
                        }
                    }
                elif conversation_context.user_preferences.get('cuisine'):
                    # New search maintaining preferences
                    return {
                        "query_text": query,
                        "location": {"city": conversation_context.current_city} if conversation_context.current_city else {},
                        "place_type": "restaurant",
                        "preferences": conversation_context.user_preferences,
                        "context": {
                            "is_rejection": False,
                            "wants_alternatives": True,
                            "specific_aspect": None,
                            "reference_to_previous": False,
                            "action_type": "new_search"
                        }
                    }

        # Handle negative responses
        if query_lower in ['no', 'nope', 'nah', "don't like", 'something else']:
            if conversation_context and conversation_context.current_place:
                return {
                    "query_text": query,
                    "location": {"city": conversation_context.current_city} if conversation_context.current_city else {},
                    "place_type": "restaurant",
                    "preferences": conversation_context.user_preferences,
                    "context": {
                        "is_rejection": True,
                        "wants_alternatives": True,
                        "specific_aspect": None,
                        "reference_to_previous": True,
                        "action_type": "get_alternatives"
                    }
                }

        # Check for specific aspect queries
        aspect_patterns = {
            'price': ['how much', 'price', 'expensive', 'cheap', 'cost'],
            'hours': ['when', 'hours', 'open', 'close', 'time'],
            'location': ['where', 'located', 'address', 'far', 'distance'],
            'menu': ['menu', 'serve', 'food', 'dish', 'eat'],
            'atmosphere': ['atmosphere', 'like', 'crowd', 'busy', 'quiet']
        }
        
        for aspect, patterns in aspect_patterns.items():
            if any(pattern in query_lower for pattern in patterns):
                if conversation_context and conversation_context.current_place:
                    return {
                        "query_text": query,
                        "location": {"city": conversation_context.current_city} if conversation_context.current_city else {},
                        "place_type": "restaurant",
                        "preferences": conversation_context.user_preferences,
                        "context": {
                            "is_rejection": False,
                            "wants_alternatives": False,
                            "specific_aspect": aspect,
                            "reference_to_previous": True,
                            "action_type": "get_aspect_details"
                        }
                    }

        # Handle comparison requests
        if any(word in query_lower for word in ['better', 'different', 'else', 'another', 'more', 'other']):
            return {
                "query_text": query,
                "location": {"city": conversation_context.current_city} if conversation_context.current_city else {},
                "place_type": "restaurant",
                "preferences": conversation_context.user_preferences,
                "context": {
                    "is_rejection": False,
                    "wants_alternatives": True,
                    "specific_aspect": None,
                    "reference_to_previous": True,
                    "action_type": "get_alternatives"
                }
            }

        # Default to standard query processing
        messages = [
            {
                "role": "system",
                "content": """
                You are a local guide helping users find places. Extract search intents and understand context.
                Consider user preferences, previous places mentioned, and conversation history.
                Return JSON with:
                {
                    "query_text": "original query",
                    "location": {"city": "city name", "state": "state"},
                    "place_type": "category",
                    "sub_type": "specific type if any",
                    "preferences": {
                        "price_level": "budget/moderate/upscale",
                        "atmosphere": ["quiet", "romantic", "casual", etc],
                        "features": ["outdoor seating", "live music", etc],
                        "cuisine": ["mexican", "italian", etc]
                    },
                    "context": {
                        "is_rejection": boolean,
                        "wants_alternatives": boolean,
                        "specific_aspect": string,
                        "reference_to_previous": boolean,
                        "action_type": "new_search"
                    }
                }
                """
            }
        ]
        
        # Add conversation context if available
        if conversation_context:
            context_prompt = f"""
            Current city: {conversation_context.current_city}
            Current place being discussed: {conversation_context.current_place['metadata']['title'] if conversation_context.current_place else 'None'}
            Recently mentioned places: {', '.join(p['metadata']['title'] for p in conversation_context.last_mentioned_places[:3])}
            User preferences: {json.dumps(conversation_context.user_preferences)}
            Previous query context: The user was looking for {', '.join(conversation_context.user_preferences.get('cuisine', []))} food
            """
            messages.append({"role": "system", "content": context_prompt})
        
        messages.append({"role": "user", "content": f"Extract from: {query}"})
        
        response = client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=messages,
            max_tokens=150,
            temperature=0.3
        )
        
        result = json.loads(response.choices[0].message.content)
        
        # Ensure query_text is always present
        if 'query_text' not in result:
            result['query_text'] = query
            
        # Maintain context for cuisine preferences
        if conversation_context and conversation_context.user_preferences.get('cuisine'):
            if 'preferences' not in result:
                result['preferences'] = {}
            if 'cuisine' not in result['preferences']:
                result['preferences']['cuisine'] = conversation_context.user_preferences['cuisine']
        
        # Ensure action_type is present
        if 'context' in result and 'action_type' not in result['context']:
            result['context']['action_type'] = 'new_search'
            
        return result
        
    except Exception as e:
        logger.error(f"Error processing query: {str(e)}")
        return {
            "query_text": query,
            "location": {},
            "place_type": "any",
            "preferences": {},
            "context": {
                "is_rejection": False,
                "wants_alternatives": False,
                "specific_aspect": None,
                "reference_to_previous": False,
                "action_type": "new_search"
            }
        }

def generate_response(query, places, conversation_context):
    """Generate natural conversational response using OpenAI"""
    try:
        # Prepare context for OpenAI
        places_context = []
        for place in places[:3]:  # Limit to top 3 places
            places_context.append({
                "name": place.metadata.get('title'),
                "rating": place.metadata.get('rating'),
                "price_level": place.metadata.get('price_level'),
                "features": place.metadata.get('features'),
                "address": place.metadata.get('address')
            })
            
        messages = [
            {
                "role": "system",
                "content": """
                You are a friendly local guide. Generate VERY concise responses about places.
                Keep responses under 100 words. Focus on key details only.
                Format:
                1. Quick intro (1 sentence)
                2. Top place highlight (1-2 sentences per place)
                3. Brief follow-up prompt
                Avoid unnecessary details or lengthy descriptions.
                """
            },
            {
                "role": "user",
                "content": f"""
                User query: {query}
                Places: {json.dumps(places_context)}
                Current city: {conversation_context.current_city}
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
        return "I found some great bars nearby. Would you like to hear about them?"

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