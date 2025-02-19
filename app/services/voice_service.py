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

logger = logging.getLogger(__name__)

# Set ElevenLabs API key
set_api_key(os.getenv('ELEVENLABS_API_KEY'))

# Cache for available voices
_available_voices = None

class ConversationContext:
    def __init__(self):
        self.last_results = []
        self.current_city = None
        self.last_query_type = None
        self.last_response = None
        self.interrupted = False
        self.speaking_state = None
        self.current_voice = None
        # Enhanced context tracking
        self.conversation_history = []  # List of all queries and responses
        self.call_start_time = None
        self.previous_queries = []
        self.previous_responses = []
        self.mentioned_places = set()  # Set of all places mentioned in the call
        self.user_preferences = {}  # Store user preferences learned during the call
        # New fields for better context
        self.current_place = None  # Currently being discussed place
        self.current_topic = None  # Current topic of conversation (e.g., 'place_details', 'searching', 'comparing')
        self.last_mentioned_places = []  # List of recently mentioned places in order
        self.discussion_depth = {}  # Track how much we've discussed each place
        # New fields for search diversity
        self.shown_places = set()  # Track all places shown to avoid repetition
        self.rejected_places = set()  # Track places user wasn't interested in
        self.preferred_places = set()  # Track places user showed interest in
        self.search_history = []  # Track search queries and their results
        self.current_search_index = 0  # Track which subset of results we're showing
        self.remaining_results = []  # Store remaining results for pagination
        
    def add_search_results(self, results, query_info):
        """Add search results and track them for diversity"""
        # Randomly shuffle results while maintaining relevance groups
        grouped_results = {}
        for result in results:
            score = round(result.score, 1)  # Group by rounded score for similar relevance
            if score not in grouped_results:
                grouped_results[score] = []
            grouped_results[score].append(result)
        
        # Shuffle within each relevance group
        shuffled_results = []
        for score in sorted(grouped_results.keys(), reverse=True):
            group = grouped_results[score]
            random.shuffle(group)
            shuffled_results.extend(group)
        
        # Filter out previously shown places
        filtered_results = [r for r in shuffled_results if r.id not in self.shown_places]
        
        # If we're running low on new places, reset the shown places
        if len(filtered_results) < 3:
            self.shown_places.clear()
            filtered_results = shuffled_results
        
        self.last_results = filtered_results[:3]  # Keep first 3 for immediate response
        self.remaining_results = filtered_results[3:]  # Store rest for pagination
        self.current_search_index = 0
        
        # Track this search
        self.search_history.append({
            'timestamp': datetime.datetime.now(),
            'query_info': query_info,
            'total_results': len(results),
            'filtered_results': len(filtered_results)
        })
        
        return self.last_results
    
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
            self.shown_places.add(result.id)
            
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
        self.discussion_depth[place_id] = self.discussion_depth.get(place_id, 0) + 1
        self.shown_places.add(place_id)  # Track that we've shown this place
        
        # Keep track of recently mentioned places
        if place_id not in [p['id'] for p in self.last_mentioned_places]:
            self.last_mentioned_places.insert(0, {
                'id': place_id,
                'metadata': place_metadata,
                'timestamp': datetime.datetime.now()
            })
            # Keep only last 5 mentioned places
            self.last_mentioned_places = self.last_mentioned_places[:5]
    
    def get_place_context(self, place_id):
        """Get context about a specific place"""
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

def format_place_results(results, query_type='default'):
    """Format place results into a natural, conversational response"""
    global conversation_context
    conversation_context.last_results = results
    conversation_context.speaking_state = 'results'
    conversation_context.current_topic = 'place_overview'
    
    if not results:
        if conversation_context.user_preferences:
            prefs = []
            if 'price' in conversation_context.user_preferences:
                prefs.append(conversation_context.user_preferences['price'])
            if 'cuisine' in conversation_context.user_preferences:
                prefs.append(', '.join(conversation_context.user_preferences['cuisine']))
            if prefs:
                return f"I couldn't find exactly what you're looking for with {' and '.join(prefs)}. Would you like me to broaden the search a bit?"
        return "I couldn't find anything matching that exactly. Could you tell me more about what you're in the mood for? I know all the best spots!"
        
    response_parts = []
    
    # Natural, conversational intros based on query type and context
    if conversation_context.current_place:
        # If we were just discussing a place, make the transition natural
        response_parts.append(f"Let me tell you about some other great options besides {conversation_context.current_place['metadata'].get('title')}!")
    else:
        # Use context-aware intros
        intros = {
            'default': ["I found some fantastic spots I think you'll love!", 
                       "Oh, I know just the places for you!",
                       "I've got some great options to share!"],
            'rating_high': ["Let me tell you about the absolute best places in town!",
                           "I've found some top-rated spots you're going to love!"],
            'rating_low': ["I know some hidden gems that are worth checking out!",
                          "Let me share some local favorites that might surprise you!"],
            'price_high': ["If you're looking for something upscale, you'll love these places!",
                          "I've found some excellent fine dining options!"],
            'price_low': ["I know some great spots that won't break the bank!",
                         "Let me tell you about some budget-friendly favorites!"],
            'most_reviews': ["These places are local favorites!",
                           "Everyone's been raving about these spots!"],
            'features': ["I found exactly what you're looking for!",
                        "These places match exactly what you want!"]
        }
        response_parts.append(random.choice(intros.get(query_type, intros['default'])))
    
    # Add each place with a more natural, conversational description
    for i, result in enumerate(results[:3], 1):
        place = result.metadata
        conversation_context.set_current_place(result.id, place)
        
        # Build engaging place description
        description = []
        
        # More natural transitions between places
        if i == 1:
            description.append(f"First, there's {place.get('title', 'Unknown')}")
        elif i == 2:
            description.append(f"Another great option is {place.get('title', 'Unknown')}")
        else:
            description.append(f"And you might also like {place.get('title', 'Unknown')}")
        
        # Add key highlights based on place type and user preferences
        if place.get('category') == 'activity':
            if place.get('description'):
                snippet = place.get('description')[:100].rsplit(' ', 1)[0] + '...'
                description.append(f"It's {snippet}")
            if place.get('features'):
                description.append(f"They offer {place.get('features')}")
        
        # Add rating and reviews naturally
        rating = float(place.get('rating', 0))
        if rating >= 4.5:
            description.append(f"People absolutely love this place")
            if place.get('reviews'):
                description.append(f"with {place.get('reviews')} glowing reviews")
        elif rating >= 4.0:
            description.append(f"It's very well-rated")
            if place.get('reviews'):
                description.append(f"with {place.get('reviews')} positive reviews")
        
        # Add price level with context
        if place.get('price_level'):
            price_descriptions = {
                '$': ["and it's quite budget-friendly", "and won't break the bank"],
                '$$': ["with moderate prices", "at a reasonable price point"],
                '$$$': ["for a more upscale experience", "if you're looking for something nicer"],
                '$$$$': ["for a really special occasion", "if you want to treat yourself"]
            }
            description.append(random.choice(price_descriptions.get(place.get('price_level'), [])))
            
        # Add location naturally
        if place.get('address'):
            street = place.get('address').split(',')[0]
            description.append(f"You'll find it on {street}")
            
        # Add atmosphere if available
        if place.get('atmosphere'):
            description.append(place.get('atmosphere'))
            
        response_parts.append(". ".join(description))
    
    # Add interactive prompt based on context
    if len(results) > 3:
        response_parts.append("I have more great places in mind too! Would you like to hear more about any of these first, or shall I continue with other options?")
    else:
        response_parts.append("Would you like to know more about any of these places? Just ask about the one you're interested in, and I can tell you about their special features, hours, or anything specific you want to know!")
    
    return " ".join(response_parts)

def format_place_details(place_id):
    """Format detailed information about a specific place"""
    global conversation_context
    conversation_context.speaking_state = 'details'
    conversation_context.current_topic = 'place_details'
    
    place_context = conversation_context.get_place_context(place_id)
    if not place_context:
        return "I'm not sure which place you're asking about. Would you like me to search for something specific?"
        
    place = place_context['metadata']
    conversation_context.set_current_place(place_id, place)
    
    details = []
    
    # Create an engaging, detailed description
    details.append(f"Let me tell you more about {place.get('title', 'this place')}!")
    
    # Add rich details based on how much we've discussed this place
    discussion_count = conversation_context.discussion_depth.get(place_id, 0)
    
    if discussion_count <= 1:
        # First time discussing this place - give overview
        if place.get('description'):
            details.append(place.get('description'))
        
        if place.get('features'):
            details.append(f"Some highlights include {place.get('features')}")
            
        if place.get('hours'):
            details.append(f"They're open {place.get('hours')}")
            
        if place.get('price_level'):
            price_desc = {
                '$': "It's very budget-friendly",
                '$$': "It's moderately priced",
                '$$$': "It's on the upscale side",
                '$$$$': "It's a high-end establishment"
            }
            details.append(price_desc.get(place.get('price_level'), ''))
    else:
        # We've discussed this place before - give more specific details
        if place.get('special_events'):
            details.append(f"They often host {place.get('special_events')}")
            
        if place.get('busy_times'):
            details.append(f"The best times to visit are {place.get('busy_times')}")
            
        if place.get('insider_tips'):
            details.append(f"Here's an insider tip: {place.get('insider_tips')}")
            
        if place.get('parking'):
            details.append(f"For parking, {place.get('parking')}")
    
    # Add contact and booking info
    if place.get('phone'):
        details.append(f"You can call them at {place.get('phone')} to make a reservation or ask questions")
        
    if place.get('website'):
        details.append(f"Check out their website at {place.get('website')} for more information")
    
    # Add interactive prompt based on context
    details.append("What specific aspect would you like to know more about? I can tell you about their prices, special features, or help you make a reservation!")
    
    return " ".join(details)

def handle_place_reference(speech_result):
    """Handle references to previously mentioned places"""
    speech_lower = speech_result.lower()
    
    # Reference keywords that might indicate user is referring to a place
    reference_keywords = [
        'that one', 'this place', 'tell me more', 'more about', 
        'what about', 'first one', 'second one', 'last one',
        'can you tell me about', 'what is', 'how is', 'the first',
        'that first', 'that place', 'this one', 'it', 'that'
    ]
    
    # Check if the speech contains any reference keywords
    contains_reference = any(keyword in speech_lower for keyword in reference_keywords)
    
    if contains_reference:
        # First check if they're referring to the current place
        if conversation_context.current_place:
            place_name = conversation_context.current_place['metadata'].get('title', '').lower()
            if place_name in speech_lower:
                return conversation_context.current_place['id']
        
        # Check for ordinal references
        if any(word in speech_lower for word in ['first', 'first one', 'that first']):
            return conversation_context.last_results[0].id if conversation_context.last_results else None
        elif any(word in speech_lower for word in ['second', 'second one']):
            return conversation_context.last_results[1].id if len(conversation_context.last_results) > 1 else None
        elif any(word in speech_lower for word in ['last', 'last one']):
            return conversation_context.last_results[-1].id if conversation_context.last_results else None
            
        # Check recently mentioned places
        for place in conversation_context.last_mentioned_places:
            place_name = place['metadata'].get('title', '').lower()
            if place_name in speech_lower:
                return place['id']
        
        # If just asking for more details about current topic
        if conversation_context.current_place and any(word in speech_lower for word in ['more', 'about', 'tell me', 'what else']):
            return conversation_context.current_place['id']
            
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
    
    # Check if user is trying to redirect the conversation
    redirect_patterns = ['but', 'actually', 'instead', 'rather', 'what about', 'can you']
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
    
    # Handle comparative questions
    comparative_patterns = ['better', 'different', 'else', 'another', 'more', 'other', 'similar', 'like this']
    if any(pattern in speech_lower for pattern in comparative_patterns):
        if conversation_context.current_place:
            return True, f"Would you like to hear about other places similar to {conversation_context.current_place['metadata'].get('title')}, or should I look for something completely different?"
        return True, "I can find you some different options. What specifically are you looking for?"
    
    # Handle clarification questions
    clarification_patterns = ['what', 'why', 'how', 'could you', 'can you', 'tell me']
    if any(pattern in speech_lower for pattern in clarification_patterns):
        if conversation_context.current_place:
            return True, f"Of course! What would you like to know more about {conversation_context.current_place['metadata'].get('title')}?"
        return True, "I'll be happy to clarify. What specifically would you like to know?"
    
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

def get_initial_greeting():
    """Get the initial greeting for first-time callers"""
    # Select a new random voice for this call
    voice_id = select_random_voice()
    name = conversation_context.current_voice['name'] if conversation_context.current_voice else "Antoni"
    
    return f"Hi! I'm {name}, your local guide. Which city can I help you explore?"

def get_location_confirmation(city, state):
    """Get confirmation message for location setting"""
    return f"Ah, {city}! I love it there! What kind of place are you looking for? I know everything from cozy cafes to the hottest bars and best restaurants!"

def get_search_acknowledgment():
    """Get acknowledgment message for starting a search"""
    return "Let me find some great spots for you!"

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