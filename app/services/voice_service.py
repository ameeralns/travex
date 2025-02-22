from elevenlabs import generate as elevenlabs_generate
from elevenlabs import set_api_key, voices, Voice
import os
import tempfile
import logging
import random
import datetime
import concurrent.futures
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json

logger = logging.getLogger(__name__)

# Set ElevenLabs API key
set_api_key(os.getenv('ELEVENLABS_API_KEY'))

# Cache for available voices
_available_voices = None

class ConversationContext:
    def __init__(self):
        """Initialize conversation context with proper data structures"""
        # Basic tracking
        self.current_city = None
        self.current_category = None
        self.current_place = None
        self.current_results = []
        self.remaining_results = []
        self.current_search_index = 0
        
        # Result tracking
        self.shown_places = set()
        self.rejected_places = set()
        self.preferred_places = set()
        self.mentioned_places = set()
        self.place_name_map = {}
        
        # Context tracking
        self.last_mentioned_places = []
        self.discussion_depth = {}
        self.category_history = []
        self.conversation_history = []
        self.user_preferences = {}
        
        # Timestamps
        self.call_start_time = datetime.datetime.now()
        self.last_interaction_time = datetime.datetime.now()
        
        # Enhanced conversation tracking
        self.conversation_flow = []  # Track conversation flow and transitions
        
        # Place and category tracking
        self.current_place = None  # Currently being discussed place
        self.current_category = None  # Current category (hotel, restaurant, etc.)
        self.category_history = []  # Track category changes
        self.last_mentioned_places = []  # List of recently mentioned places in order
        self.discussion_depth = {}  # Track how much we've discussed each place
        self.place_name_map = {}  # Map place names to IDs
        
        # User understanding
        self.user_interests = set()  # Track what the user seems interested in
        self.rejected_topics = set()  # Track what the user isn't interested in
        self.interaction_style = {
            'verbose': False,  # Does user prefer detailed responses
            'direct': False,   # Does user prefer direct answers
            'exploratory': False  # Does user like to explore options
        }
        
        # Search management
        self.search_history = []  # Track search queries and their results
        self.current_topic = None  # Current topic of conversation
        self.topic_history = []  # Track topic changes
        self.last_action = None  # Last action taken
        self.pending_questions = []  # Questions we haven't answered yet
        
    def update_interaction_style(self, query, response_type):
        """Learn user's preferred interaction style"""
        query_lower = query.lower()
        
        # Check for verbosity preference
        if any(phrase in query_lower for phrase in ['tell me more', 'details', 'explain']):
            self.interaction_style['verbose'] = True
        elif any(phrase in query_lower for phrase in ['quick', 'brief', 'just']):
            self.interaction_style['verbose'] = False
            
        # Check for directness preference
        if any(phrase in query_lower for phrase in ['exactly', 'specifically', 'precisely']):
            self.interaction_style['direct'] = True
            
        # Check for exploratory nature
        if any(phrase in query_lower for phrase in ['what else', 'other options', 'alternatives']):
            self.interaction_style['exploratory'] = True
            
    def add_to_conversation_flow(self, query, response_type, action_taken):
        """Track conversation flow for better context understanding"""
        self.conversation_flow.append({
            'timestamp': datetime.datetime.now(),
            'query': query,
            'response_type': response_type,
            'action_taken': action_taken,
            'category': self.current_category,
            'topic': self.current_topic
        })
        
    def should_maintain_context(self, query_lower, intent_analysis):
        """Enhanced context maintenance decision"""
        # If we're in the middle of discussing places of a certain category
        if not self.current_category:
            return False
            
        # Consider conversation flow
        if self.conversation_flow:
            last_interaction = self.conversation_flow[-1]
            # If we were just giving details about a place
            if last_interaction['action_taken'] == 'get_place_details':
                return True
                
        # Keywords that suggest category change
        category_change_keywords = [
            'instead', 'different', 'change', 'switch', 'looking for',
            'want to find', 'search for', 'find me', 'show me'
        ]
        
        # If query contains explicit category changes, don't maintain
        if any(keyword in query_lower for keyword in category_change_keywords):
            return False
            
        # Keywords that suggest maintaining context
        maintain_context_keywords = [
            'this', 'that', 'it', 'there', 'more about',
            'tell me more', 'what about', 'how about'
        ]
        
        # Consider intent analysis confidence
        if intent_analysis and intent_analysis.get('should_maintain_context'):
            return True
            
        return any(keyword in query_lower for keyword in maintain_context_keywords)
        
    def update_topic(self, new_topic):
        """Update conversation topic with history tracking"""
        if self.current_topic != new_topic:
            self.topic_history.append({
                'from_topic': self.current_topic,
                'to_topic': new_topic,
                'timestamp': datetime.datetime.now()
            })
            self.current_topic = new_topic
            
    def get_conversation_context(self):
        """Get rich conversation context for AI"""
        return {
            'city': self.current_city,
            'current_category': self.current_category,
            'current_place': self.current_place['metadata'] if self.current_place else None,
            'current_topic': self.current_topic,
            'interaction_style': self.interaction_style,
            'user_preferences': self.user_preferences,
            'conversation_flow': self.conversation_flow[-3:] if self.conversation_flow else [],
            'topic_history': self.topic_history[-3:] if self.topic_history else []
        }
    
    def add_search_results(self, results, query_info):
        """Add search results to conversation context with proper format handling"""
        try:
            if not results:
                return []
                
            processed_results = []
            for result in results:
                # Handle both dictionary and object formats
                if isinstance(result, dict):
                    processed_result = result
                else:
                    processed_result = {
                        'id': result.id,
                        'metadata': result.metadata,
                        'score': getattr(result, 'score', 0)
                    }
                processed_results.append(processed_result)
            
            # Store the first three results for immediate use
            self.current_results = processed_results[:3]
            
            # Store remaining results for future reference
            self.remaining_results = processed_results[3:]
            
            # Reset search index
            self.current_search_index = 0
            
            # Update place tracking
            for result in self.current_results:
                self.mentioned_places.add(result['id'])
                if result.get('metadata', {}).get('title'):
                    self.place_name_map[result['metadata']['title'].lower()] = result['id']
            
            # Set the first result as current place
            if self.current_results:
                self.set_current_place(
                    self.current_results[0]['id'],
                    self.current_results[0].get('metadata', {})
                )
            
            # Log the results
            logger.info(f"Added {len(self.current_results)} results to conversation context")
            if self.current_place:
                logger.info(f"Current place: {self.current_place.get('metadata', {}).get('title')}")
            
            return self.current_results
            
        except Exception as e:
            logger.error(f"Error adding search results: {str(e)}")
            logger.exception("Full error traceback:")
            return []
    
    def get_next_results(self, count=3):
        """Get next batch of results, ensuring we don't repeat places"""
        if not self.remaining_results:
            return []
            
        start_idx = self.current_search_index
        end_idx = start_idx + count
        results = self.remaining_results[start_idx:end_idx]
        self.current_search_index = end_idx
        
        # Track these places as shown
        for result in results:
            self.shown_places.add(result['id'])
            
        return results
    
    def mark_place_rejected(self, place_id):
        """Mark a place as rejected by the user"""
        self.rejected_places.add(place_id)
        if place_id in self.preferred_places:
            self.preferred_places.remove(place_id)
    
    def mark_place_preferred(self, place_id):
        """Mark a place as preferred by the user"""
        self.preferred_places.add(place_id)
        if place_id in self.rejected_places:
            self.rejected_places.remove(place_id)
    
    def set_current_place(self, place_id, place_metadata):
        """Set the currently discussed place and update context"""
        self.current_place = {
            'id': place_id,
            'metadata': place_metadata,
            'first_mentioned': datetime.datetime.now(),
            'mentioned_count': self.discussion_depth.get(place_id, 0) + 1
        }
        # Update category tracking
        if 'category' in place_metadata:
            self.current_category = place_metadata['category']
            self.category_history.append({
                'category': place_metadata['category'],
                'timestamp': datetime.datetime.now()
            })
        
        self.discussion_depth[place_id] = self.discussion_depth.get(place_id, 0) + 1
        self.shown_places.add(place_id)
        
        if place_id not in [p['id'] for p in self.last_mentioned_places]:
            self.last_mentioned_places.insert(0, {
                'id': place_id,
                'metadata': place_metadata,
                'timestamp': datetime.datetime.now()
            })
            self.last_mentioned_places = self.last_mentioned_places[:5]
    
    def get_current_category(self):
        """Get the current category being discussed"""
        return self.current_category

    def clear_category(self):
        """Clear the current category when explicitly changing topics"""
        self.current_category = None
    
    def get_place_context(self, place_id):
        """Get context for a specific place"""
        if self.current_place and self.current_place['id'] == place_id:
            return self.current_place
            
        for place in self.last_mentioned_places:
            if place['id'] == place_id:
                return place
                
        return None

# Global conversation context
conversation_context = ConversationContext()

def initialize_voices():
    """Initialize and cache available ElevenLabs voices"""
    global _available_voices
    try:
        logger.info("🎙️ Initializing ElevenLabs voices...")
        all_voices = voices()
        if not all_voices:
            logger.error("❌ No voices found in ElevenLabs account")
            return False
            
        # Filter out test voices and cache the production ones
        _available_voices = [
            {
                'id': voice.voice_id,
                'name': voice.name,
                'category': getattr(voice, 'category', 'general'),
                'description': getattr(voice, 'description', '')
            }
            for voice in all_voices
            if not voice.name.lower().startswith('test')
        ]
        
        voice_names = [v['name'] for v in _available_voices]
        logger.info(f"✅ Successfully initialized {len(_available_voices)} voices: {', '.join(voice_names)}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize ElevenLabs voices: {str(e)}")
        logger.exception("Full error traceback:")
        return False

def get_available_voices():
    """Get the list of available voices, initializing if necessary"""
    global _available_voices
    if _available_voices is None:
        initialize_voices()
    return _available_voices or []

def select_random_voice():
    """Select a random voice from available ElevenLabs voices"""
    try:
        available = get_available_voices()
        if not available:
            logger.warning("No ElevenLabs voices found, using fallback voice")
            # Set a basic fallback voice in the context
            conversation_context.current_voice = {
                'id': "ErXwobaYiN019PkySvjV",  # Antoni voice ID
                'name': "Antoni"
            }
            return "ErXwobaYiN019PkySvjV"
            
        # Select a random voice
        selected = random.choice(available)
        logger.info(f"Selected voice: {selected['name']} ({selected['id']})")
        
        # Store in conversation context
        conversation_context.current_voice = {
            'id': selected['id'],
            'name': selected['name']
        }
        
        return selected['id']
        
    except Exception as e:
        logger.error(f"❌ Error selecting voice: {str(e)}")
        logger.exception("Full error traceback:")
        # Fallback to Antoni
        conversation_context.current_voice = {
            'id': "ErXwobaYiN019PkySvjV",
            'name': "Antoni"
        }
        return "ErXwobaYiN019PkySvjV"

def chunk_response(text, chunk_size=75):
    """Break long responses into smaller, interruptible chunks"""
    # Use smaller chunks for faster generation
    sentences = text.split('. ')
    chunks = []
    current_chunk = []
    current_length = 0
    
    for sentence in sentences:
        # Clean and normalize the sentence
        sentence = sentence.strip()
        if not sentence:
            continue
            
        # If this sentence would make the chunk too long, save current chunk
        if current_length + len(sentence) > chunk_size and current_chunk:
            chunks.append('. '.join(current_chunk) + '.')
            current_chunk = []
            current_length = 0
            
        current_chunk.append(sentence)
        current_length += len(sentence)
    
    # Add any remaining sentences
    if current_chunk:
        chunks.append('. '.join(current_chunk) + '.')
    
    # Ensure chunks aren't too small but also not too large
    return [chunk for chunk in chunks if 15 <= len(chunk) <= 100]

def get_initial_greeting():
    """Generate initial greeting with personality"""
    greetings = [
        "Hi! I'm your local guide. Which city can I help you explore?",
        "Hello! I'm here to help you discover great places. What city are you interested in?",
        "Welcome! I'm your personal local guide. Which city would you like to explore?"
    ]
    return random.choice(greetings)

def get_location_confirmation(city, state=None):
    """Generate location confirmation with personality"""
    responses = [
        f"Great! I know {city} very well. What type of place are you looking for?",
        f"Excellent choice! I love {city}. What would you like to discover?",
        f"Perfect! I can help you find the best places in {city}. What interests you?"
    ]
    return random.choice(responses)

def get_search_acknowledgment():
    """Generate search acknowledgment with personality"""
    responses = [
        "Just a moment while I find the perfect places for you...",
        "Let me search for some great options...",
        "I'll help you find exactly what you're looking for..."
    ]
    return random.choice(responses)

def format_place_results(results, conversation_context=None):
    """Format place results into natural conversation"""
    try:
        if not results:
            return "I couldn't find any places matching your criteria. Would you like to try a different search?"
            
        # Get place type for context
        place_type = results[0]['metadata'].get('category', 'place').lower()
        
        # Special handling for outdoor/trail results
        if place_type in ['trail', 'park', 'hiking trail', 'outdoor recreation']:
            intro = "I found some great outdoor spots that might be perfect for you"
            if conversation_context and conversation_context.has_family_context():
                intro += " and your family"
            intro += ". "
            
            details = []
            for result in results[:3]:
                place_info = []
                place_info.append(result['metadata'].get('title', 'this place'))
                
                # Add difficulty level if available
                if 'difficulty' in result['metadata']:
                    place_info.append(f"it's a {result['metadata']['difficulty']} trail")
                
                # Add length if available
                if 'length' in result['metadata']:
                    place_info.append(f"about {result['metadata']['length']} long")
                
                # Add key features
                features = []
                if result['metadata'].get('features'):
                    feature_list = result['metadata']['features']
                    if isinstance(feature_list, str):
                        feature_list = feature_list.split(',')
                    important_features = [f for f in feature_list if f.lower() in 
                        ['parking', 'restrooms', 'water fountain', 'playground', 'picnic area']]
                    if important_features:
                        features.extend(important_features)
                
                if features:
                    place_info.append(f"with {', '.join(features)}")
                
                # Add rating
                if result['metadata'].get('rating'):
                    rating = float(result['metadata']['rating'])
                    if rating >= 4.5:
                        place_info.append("highly rated by visitors")
                    elif rating >= 4.0:
                        place_info.append("well rated by visitors")
                
                details.append(". ".join(place_info))
            
            response = intro + " " + ". Next, ".join(details) + "."
            
            # Add helpful context for families
            if conversation_context and conversation_context.has_family_context():
                response += " All these places are family-friendly and have good accessibility."
            
            response += " Would you like to know more about any of these places?"
            
            return response
            
        # Handle other place types with existing logic
        intro = f"I found some great {place_type}s that you might like. "
        details = []
        for result in results[:3]:
            place_info = []
            place_info.append(result['metadata'].get('title', 'this place'))
            
            if result['metadata'].get('price_level'):
                place_info.append(f"it's {result['metadata']['price_level']} priced")
            
            if result['metadata'].get('rating'):
                rating = float(result['metadata']['rating'])
                if rating >= 4.5:
                    place_info.append("highly rated")
                elif rating >= 4.0:
                    place_info.append("well rated")
            
            if result['metadata'].get('features'):
                features = result['metadata']['features']
                if isinstance(features, str):
                    features = features.split(',')
                top_features = features[:2]
                if top_features:
                    place_info.append(f"featuring {', '.join(top_features)}")
            
            details.append(". ".join(place_info))
        
        response = intro + " " + ". Next, ".join(details) + "."
        response += " Would you like to know more about any of these places?"
        
        return response
        
    except Exception as e:
        logger.error(f"Error formatting place results: {str(e)}")
        return "I found some places that match your criteria. Would you like me to tell you about them?"

def format_place_details(place_metadata):
    """Format detailed place information conversationally"""
    response = []
    
    # Basic information
    response.append(f"Let me tell you more about {place_metadata.get('title')}. ")
    
    # Location and contact
    if place_metadata.get('address'):
        response.append(f"It's located at {place_metadata['address']}. ")
    if place_metadata.get('phone'):
        response.append(f"You can reach them at {place_metadata['phone']}. ")
    
    # Hours
    if place_metadata.get('hours'):
        try:
            hours = json.loads(place_metadata['hours'])
            today = datetime.now().strftime('%A')
            if today in hours:
                response.append(f"Today they're open {hours[today]}. ")
        except:
            pass
    
    # Features and amenities
    if place_metadata.get('about'):
        try:
            about = json.loads(place_metadata['about'])
            features = [feature for feature in about if feature.get('enabled', True)]
            if features:
                response.append("Some notable features include: ")
                response.append(", ".join(f.get('name', '') for f in features[:3]))
                response.append(". ")
        except:
            pass
    
    # Reviews and rating
    if place_metadata.get('rating') and place_metadata.get('review_count'):
        response.append(
            f"It has {place_metadata['rating']} stars based on "
            f"{place_metadata['review_count']} reviews. "
        )
    
    # Add call to action
    response.append(
        "Would you like to hear about more places like this, "
        "or would you like to explore something different?"
    )
    
    return "".join(response)

def handle_farewell():
    """Generate farewell message"""
    farewells = [
        "It was great helping you today! Feel free to ask me about any other places you'd like to discover.",
        "I enjoyed being your guide! Don't hesitate to ask if you need more recommendations.",
        "Thanks for letting me help! I'm always here when you need to find great places to visit."
    ]
    return random.choice(farewells)

def handle_place_reference(self, speech_result):
    """Handle references to previously mentioned places"""
    try:
        speech_lower = speech_result.lower()
        logger.info(f"\n=== Processing Place Reference ===")
        logger.info(f"🎯 Input speech: '{speech_lower}'")
        
        # Reference keywords that indicate user is referring to a place
        reference_keywords = [
            'that one', 'this place', 'tell me more', 'more about', 
            'what about', 'first one', 'second one', 'last one', 'third one',
            'can you tell me about', 'what is', 'how is', 'the first',
            'that first', 'that place', 'this one', 'it', 'that',
            'first restaurant', 'second restaurant', 'third restaurant',
            'first place', 'second place', 'third place'
        ]
        logger.info(f"🔍 Checking against {len(reference_keywords)} reference patterns")
        
        # Ordinal number mapping (0-based index)
        ordinal_mapping = {
            'first': 0, '1st': 0, 'one': 0,
            'second': 1, '2nd': 1, 'two': 1,
            'third': 2, '3rd': 2, 'three': 2,
            'last': -1
        }
        
        # Check if they're referring to the current place
        if self.current_place and isinstance(self.current_place, dict):
            current_title = self.current_place.get('metadata', {}).get('title', '').lower()
            logger.info(f"📍 Current place in context: '{current_title}'")
            
            if current_title and (current_title in speech_lower or 
                any(word in current_title for word in speech_lower.split() if len(word) > 3)):
                logger.info(f"✅ Matched current place reference: {current_title}")
                return self.current_place.get('id')
        else:
            logger.info("ℹ️ No current place in context")
        
        # Check for ordinal references in current results
        if self.current_results:
            logger.info(f"🔢 Checking ordinal references against {len(self.current_results)} current results")
            for ordinal, index in ordinal_mapping.items():
                if ordinal in speech_lower:
                    logger.info(f"📊 Found ordinal reference: '{ordinal}' (index: {index})")
                    if index == -1:
                        index = len(self.current_results) - 1
                    if 0 <= index < len(self.current_results):
                        result = self.current_results[index]
                        if isinstance(result, dict):
                            title = result.get('metadata', {}).get('title', '')
                            logger.info(f"✅ Matched ordinal reference to: {title}")
                            self.set_current_place(result.get('id'), result.get('metadata', {}))
                            return result.get('id')
        else:
            logger.info("ℹ️ No current results to check ordinal references against")
        
        # Check for partial name matches in all results
        speech_words = [word for word in speech_lower.split() if len(word) > 3]
        all_results = self.current_results + (self.remaining_results or [])
        
        if speech_words:
            logger.info(f"🔤 Checking partial name matches with words: {speech_words}")
            
            for result in all_results:
                if isinstance(result, dict):
                    title = result.get('metadata', {}).get('title', '').lower()
                    if title and any(word in title for word in speech_words):
                        logger.info(f"✅ Found partial name match: '{title}'")
                        self.set_current_place(result.get('id'), result.get('metadata', {}))
                        return result.get('id')
        
        # Check place name map for exact matches
        if hasattr(self, 'place_name_map'):
            logger.info(f"📚 Checking exact matches in place name map ({len(self.place_name_map)} entries)")
            for name, place_id in self.place_name_map.items():
                if name.lower() in speech_lower:
                    logger.info(f"✅ Found exact name match: '{name}'")
                    for result in all_results:
                        if isinstance(result, dict) and result.get('id') == place_id:
                            self.set_current_place(result.get('id'), result.get('metadata', {}))
                            return place_id
        
        logger.info("❌ No place reference found in speech")
        return None
        
    except Exception as e:
        logger.error(f"❌ Error handling place reference: {str(e)}")
        logger.exception("Full error traceback:")
        return None

def handle_interruption(speech_result):
    """Handle user interruptions and follow-up questions"""
    speech_lower = speech_result.lower()
    
    # Common interruption patterns with more natural language
    stop_patterns = ['stop', 'wait', 'hold on', 'pause', 'excuse me', 'hang on', 'one second', 'just a minute']
    
    # Check for direct interruptions first
    if any(pattern in speech_lower for pattern in stop_patterns):
        conversation_context.interrupted = True
        return True, "Of course! I'll pause right there. What would you like to know?"
    
    # Don't treat place inquiries as interruptions
    place_inquiry_patterns = [
        'tell me more about', 'what about', 'can you tell me about',
        'more information', 'details about', 'tell me about',
        'first', 'second', 'third', 'last', 'that one'
    ]
    if any(pattern in speech_lower for pattern in place_inquiry_patterns):
        return False, None
    
    # Check if user is trying to redirect the conversation
    redirect_patterns = ['but', 'actually', 'instead', 'rather']
    if any(pattern in speech_lower for pattern in redirect_patterns):
        conversation_context.interrupted = True
        return True, "Let me address that for you instead. What would you like to know?"
    
    # Question about a specific aspect of the current place
    if conversation_context.current_place:
        place = conversation_context.current_place['metadata']
        
        aspect_patterns = {
            'price': ['how much', 'price', 'expensive', 'cheap', 'cost', 'pricing', 'budget'],
            'hours': ['when', 'hours', 'open', 'close', 'time', 'today', 'tomorrow', 'weekend'],
            'location': ['where', 'located', 'address', 'far', 'distance', 'get there', 'directions'],
            'menu': ['menu', 'serve', 'food', 'dish', 'specialty', 'eat', 'cuisine', 'options'],
            'reservation': ['reserve', 'book', 'reservation', 'table', 'tonight', 'available'],
            'atmosphere': ['atmosphere', 'like', 'crowd', 'busy', 'quiet', 'romantic', 'family'],
            'parking': ['parking', 'park', 'garage', 'valet'],
            'reviews': ['reviews', 'ratings', 'people say', 'popular', 'recommend']
        }
        
        for aspect, patterns in aspect_patterns.items():
            if any(pattern in speech_lower for pattern in patterns):
                if aspect == 'price':
                    price_desc = {
                        '$': "It's very budget-friendly",
                        '$$': "It's moderately priced",
                        '$$$': "It's on the upscale side",
                        '$$$$': "It's a high-end establishment"
                    }
                    response = price_desc.get(place.get('price_level'), "I don't have exact price information, but I can find similar restaurants in your preferred price range.")
                    return True, f"{response} Would you like to know anything else about {place.get('title')}?"
                    
                elif aspect == 'hours':
                    hours = place.get('hours')
                    if hours:
                        return True, f"They're open {hours}. Would you like me to check if they're busy right now?"
                    return True, "Let me check their current hours for you. Would you like me to call them?"
                    
                elif aspect == 'location':
                    address = place.get('address')
                    if address:
                        return True, f"It's located at {address}. Would you like directions or should I find something closer to you?"
                    return True, "Let me get you the exact location. Would you prefer walking or driving directions?"
                    
                elif aspect == 'menu':
                    desc = place.get('description', '')
                    features = place.get('features', '')
                    response = f"Let me tell you about their food. {desc} {features}".strip()
                    return True, f"{response} Would you like to know about any specific dishes or dietary options?"
                    
                elif aspect == 'reservation':
                    phone = place.get('phone')
                    if phone:
                        return True, f"I can help you make a reservation. Their number is {phone}. Would you like me to call them for you?"
                    return True, "I can help you book a table. What time were you thinking of going?"
                    
                elif aspect == 'atmosphere':
                    atmosphere = place.get('atmosphere', 'It has a great ambiance')
                    return True, f"{atmosphere}. Are you looking for something specific in terms of atmosphere?"
                    
                elif aspect == 'parking':
                    parking = place.get('parking', "Let me check their parking situation for you")
                    return True, f"{parking}. Would you like me to find places with easier parking?"
                    
                elif aspect == 'reviews':
                    rating = place.get('rating')
                    reviews = place.get('reviews')
                    if rating and reviews:
                        return True, f"It has {rating} stars from {reviews} reviews. Would you like to hear what people specifically love about it?"
                    return True, "Let me check what recent visitors have said about it. Any specific aspects you're curious about?"
    
    return False, None

def generate_voice_response(text, voice_name=None, conversation_type="initial"):
    """Generate voice response using ElevenLabs with parallel processing"""
    try:
        conversation_context.last_response = text
        voice_id = conversation_context.current_voice['id'] if conversation_context.current_voice else select_random_voice()
        
        # Break response into smaller chunks
        chunks = chunk_response(text)
        responses = []
        
        temp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'temp_audio')
        os.makedirs(temp_dir, exist_ok=True)
        
        logger.info(f"Generating {len(chunks)} audio chunks")
        
        def generate_chunk(chunk_data):
            chunk, index = chunk_data
            try:
                if not chunk or len(chunk.strip()) < 10:
                    return None
                    
                audio = elevenlabs_generate(
                    text=chunk,
                    voice=voice_id,
                    model="eleven_monolingual_v1"
                )
                
                if not audio:
                    logger.error(f"Failed to generate audio for chunk {index+1}")
                    return None
                
                temp_filename = f"audio_{os.urandom(8).hex()}.mp3"
                temp_path = os.path.join(temp_dir, temp_filename)
                
                with open(temp_path, 'wb') as temp_file:
                    temp_file.write(audio)
                
                if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                    logger.info(f"Successfully generated chunk {index+1}/{len(chunks)}")
                    return temp_path
                return None
                
            except Exception as e:
                logger.error(f"Error processing chunk {index+1}: {str(e)}")
                return None
        
        # Process chunks in batches of 2 to respect concurrent request limit
        batch_size = 2
        for i in range(0, len(chunks), batch_size):
            batch_chunks = chunks[i:i + batch_size]
            
            # Use ThreadPoolExecutor for parallel processing of current batch
            with ThreadPoolExecutor(max_workers=batch_size) as executor:
                batch_futures = list(executor.map(
                    generate_chunk,
                    [(chunk, i + idx) for idx, chunk in enumerate(batch_chunks)]
                ))
                
                # Add successful responses from this batch
                responses.extend([r for r in batch_futures if r is not None])
        
        if not responses:
            logger.error("No audio responses were generated successfully")
            error_message = "I apologize, but I'm having trouble speaking. Let me try again with a simpler response."
            return [generate_error_audio(error_message, temp_dir)]
            
        return responses
            
    except Exception as e:
        logger.error(f"❌ Error generating voice response: {str(e)}")
        logger.exception("Full error traceback:")
        error_message = "I'm having trouble speaking right now. Please try again."
        return [generate_error_audio(error_message, temp_dir)]

def generate_error_audio(error_message, temp_dir):
    """Generate a simple error message audio file"""
    try:
        # Use Antoni voice for error messages - more reliable
        audio = elevenlabs_generate(
            text=error_message,
            voice="ErXwobaYiN019PkySvjV",  # Antoni voice
            model="eleven_monolingual_v1"
        )
        
        if not audio:
            logger.error("Failed to generate error audio")
            return None
            
        temp_filename = f"error_audio_{os.urandom(8).hex()}.mp3"
        temp_path = os.path.join(temp_dir, temp_filename)
        
        with open(temp_path, 'wb') as temp_file:
            temp_file.write(audio)
            
        if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
            logger.error("Failed to create valid error audio file")
            return None
            
        return temp_path
        
    except Exception as e:
        logger.error(f"Failed to generate error audio: {str(e)}")
        return None

def cleanup_audio_file(file_path):
    """Clean up temporary audio file"""
    try:
        if file_path and os.path.exists(file_path):
            logger.info(f"🗑️ Cleaning up audio file: {file_path}")
            os.unlink(file_path)
            logger.debug("Audio file successfully deleted")
    except Exception as e:
        logger.error(f"❌ Error cleaning up audio file: {str(e)}")
        logger.exception("Full error traceback:")

def add_to_history(query, response, query_type='user_query'):
    """Add interaction to conversation history with timestamp"""
    conversation_context.conversation_history.append({
        'timestamp': datetime.datetime.now(),
        'query': query,
        'response': response,
        'type': query_type
    })
    
    # Update previous queries and responses
    if query:
        conversation_context.previous_queries.append(query)
    if response:
        conversation_context.previous_responses.append(response)
        
    # Learn from the interaction
    if query_type == 'user_query':
        _update_preferences_from_query(query)

def _update_preferences_from_query(query):
    """Learn user preferences from their queries"""
    query_lower = query.lower()
    
    # Price preferences
    price_patterns = {
        'cheap': 'budget',
        'expensive': 'upscale',
        'affordable': 'budget',
        'fancy': 'upscale',
        'high-end': 'upscale'
    }
    
    # Cuisine preferences
    cuisine_words = ['mexican', 'italian', 'chinese', 'indian', 'japanese', 'thai', 'mediterranean']
    
    # Atmosphere preferences
    atmosphere_patterns = {
        'quiet': 'quiet',
        'romantic': 'romantic',
        'casual': 'casual',
        'family': 'family-friendly',
        'outdoor': 'outdoor',
        'rooftop': 'rooftop'
    }
    
    # Update preferences based on the query
    for pattern, pref in price_patterns.items():
        if pattern in query_lower:
            conversation_context.user_preferences['price'] = pref
            
    for cuisine in cuisine_words:
        if cuisine in query_lower:
            if 'cuisine' not in conversation_context.user_preferences:
                conversation_context.user_preferences['cuisine'] = []
            if cuisine not in conversation_context.user_preferences['cuisine']:
                conversation_context.user_preferences['cuisine'].append(cuisine)
                
    for pattern, pref in atmosphere_patterns.items():
        if pattern in query_lower:
            if 'atmosphere' not in conversation_context.user_preferences:
                conversation_context.user_preferences['atmosphere'] = []
            if pref not in conversation_context.user_preferences['atmosphere']:
                conversation_context.user_preferences['atmosphere'].append(pref)

def update_user_preferences(preferences):
    """Update user preferences based on their queries"""
    conversation_context.user_preferences.update(preferences)

def add_mentioned_place(place_id, place_name):
    """Track mentioned places for better context"""
    conversation_context.mentioned_places.add((place_id, place_name))

def get_conversation_summary():
    """Get a summary of the entire conversation"""
    return {
        'city': conversation_context.current_city,
        'query_count': len(conversation_context.previous_queries),
        'mentioned_places': list(conversation_context.mentioned_places),
        'preferences': conversation_context.user_preferences,
        'last_query_type': conversation_context.last_query_type
    } 