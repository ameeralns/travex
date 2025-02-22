from flask import Blueprint, request, send_from_directory, url_for
import os
import logging
from pathlib import Path
from datetime import datetime
from app.services.voice_service import (
    generate_voice_response, get_initial_greeting,
    get_location_confirmation, get_search_acknowledgment,
    format_place_results, format_place_details, cleanup_audio_file,
    handle_place_reference, conversation_context, handle_interruption,
    add_to_history, update_user_preferences, add_mentioned_place,
    get_conversation_summary
)
from app.services.openai_service import process_user_query, generate_response, handle_aspect_query
from app.services.pinecone_service import search_places, get_place_details, search_by_attribute
from twilio.twiml.voice_response import VoiceResponse, Gather
import json

main = Blueprint('main', __name__)
logger = logging.getLogger(__name__)

# Create a directory for temporary audio files
TEMP_AUDIO_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'temp_audio')
os.makedirs(TEMP_AUDIO_DIR, exist_ok=True)

@main.route("/voice", methods=['GET', 'POST'])
def voice():
    """Handle incoming calls"""
    resp = VoiceResponse()
    
    try:
        logger.info("📞 NEW CALL INITIATED")
        logger.info("=== Call Setup ===")
        
        # Initialize conversation context for new call
        conversation_context.conversation_history = []
        conversation_context.call_start_time = datetime.now()
        conversation_context.previous_queries = []
        conversation_context.previous_responses = []
        conversation_context.mentioned_places = set()
        conversation_context.user_preferences = {}
        conversation_context.current_voice = None
        
        logger.info("✅ Conversation context initialized")
        
        # Initial greeting with new random voice
        greeting = get_initial_greeting()
        logger.info(f"🗣️ AI: '{greeting}'")
        greeting_audio_paths = generate_voice_response(greeting)
        
        if not greeting_audio_paths:
            logger.error("❌ Failed to generate greeting audio")
            resp.say("I apologize, but I'm having trouble connecting. Please try again later.")
            return str(resp)
            
        logger.info("✅ Greeting audio generated successfully")
        
        # Play the greeting audio
        audio_filename = os.path.basename(greeting_audio_paths[0])
        resp.play(url_for('main.serve_audio', filename=audio_filename))
        
        # Add initial greeting to history
        add_to_history('call_start', greeting, 'system_greeting')
        
        # Gather city information
        gather = Gather(
            input='speech',
            action='/voice/process',
            timeout=5,
            speechTimeout='auto',
            maxTimeout=30,
            interruptible=True
        )
        resp.append(gather)
        
        logger.info("⏳ Waiting for user response...")
        return str(resp)
        
    except Exception as e:
        logger.error(f"❌ Error in voice route: {str(e)}")
        logger.exception("Full error traceback:")
        resp.say("I apologize, but I'm having trouble connecting. Please try again later.")
        return str(resp)

@main.route("/voice/process", methods=['POST'])
def process_voice():
    """Process incoming voice request with enhanced intelligence"""
    resp = VoiceResponse()
    
    try:
        speech_result = request.values.get('SpeechResult', '')
        logger.info("\n=== Processing User Input ===")
        logger.info(f"👤 User: '{speech_result}'")
        
        if not speech_result:
            logger.warning("⚠️ No speech detected")
            return handle_no_speech_result(resp)
            
        # Add to conversation history
        add_to_history(speech_result, None, 'user_query')
        logger.info("✅ Added to conversation history")
        
        # Process query with new intelligence layer
        logger.info("🔍 Processing query...")
        query_info = process_user_query(speech_result, conversation_context)
        logger.info(f"📊 Query Info: {json.dumps(query_info, indent=2)}")
        
        # Extract and set city if present in query
        if query_info['location'].get('city'):
            city = query_info['location']['city']
            conversation_context.current_city = city
            logger.info(f"🌆 Setting city to: {city}")
        
        # If we have both city and place type, proceed with search
        if conversation_context.current_city:
            # Ensure location is properly set in query_info
            query_info['location']['city'] = conversation_context.current_city
            
            if query_info['place_type'] != 'place':
                logger.info(f"🎯 Proceeding with search for {query_info['place_type']} in {conversation_context.current_city}")
                return handle_place_search(resp, query_info)
            else:
                # Only ask for place type if none detected
                response_text = get_location_confirmation(conversation_context.current_city)
                logger.info(f"🗣️ AI: '{response_text}'")
                audio_paths = generate_voice_response(response_text)
                if audio_paths:
                    for audio_path in audio_paths:
                        resp.play(url_for('main.serve_audio', filename=os.path.basename(audio_path)))
                
                gather = Gather(
                    input='speech',
                    action='/voice/process',
                    timeout=2,
                    speechTimeout='auto',
                    maxTimeout=30,
                    interruptible=True
                )
                resp.append(gather)
                logger.info("⏳ Waiting for place type...")
                return str(resp)
        else:
            # If no city detected, ask for city
            response_text = "Which city would you like to explore?"
            logger.info(f"🗣️ AI: '{response_text}'")
            audio_paths = generate_voice_response(response_text)
            if audio_paths:
                for audio_path in audio_paths:
                    resp.play(url_for('main.serve_audio', filename=os.path.basename(audio_path)))
            
            gather = Gather(
                input='speech',
                action='/voice/process',
                timeout=2,
                speechTimeout='auto',
                maxTimeout=30,
                interruptible=True
            )
            resp.append(gather)
            logger.info("⏳ Waiting for city...")
            return str(resp)
        
    except Exception as e:
        logger.error(f"❌ Error processing voice request: {str(e)}")
        logger.exception("Full error traceback:")
        error_response = "I apologize, but I'm having trouble processing your request. Could you try again?"
        logger.info(f"🗣️ AI: '{error_response}'")
        audio_paths = generate_voice_response(error_response)
        if audio_paths:
            for audio_path in audio_paths:
                resp.play(url_for('main.serve_audio', filename=os.path.basename(audio_path)))
        
        gather = Gather(
            input='speech',
            action='/voice/process',
            timeout=2,
            speechTimeout='auto',
            maxTimeout=30,
            interruptible=True
        )
        resp.append(gather)
        logger.info("⏳ Waiting for retry...")
        return str(resp)

def handle_place_search(resp, query_info):
    """Handle place search with proper context"""
    logger.info("🔍 Starting place search...")
    ack_response = get_search_acknowledgment()
    logger.info(f"🗣️ AI: '{ack_response}'")
    audio_paths = generate_voice_response(ack_response, conversation_type="searching")
    if audio_paths:
        for audio_path in audio_paths:
            resp.play(url_for('main.serve_audio', filename=os.path.basename(audio_path)))
    
    # Perform search
    logger.info("🔎 Executing search...")
    results = search_places(
        query_info,
        excluded_ids=conversation_context.rejected_places if conversation_context else None,
        top_k=5,
        sort_by='best_match'
    )
    
    if results:
        logger.info(f"✅ Found {len(results)} results")
        response_text = format_place_results(results)
        logger.info(f"🗣️ AI: '{response_text}'")
        audio_paths = generate_voice_response(response_text)
        if audio_paths:
            for audio_path in audio_paths:
                resp.play(url_for('main.serve_audio', filename=os.path.basename(audio_path)))
    else:
        logger.warning("⚠️ No results found")
        no_results_response = f"I couldn't find any {query_info['place_type']}s matching your criteria. Would you like to try a different search?"
        logger.info(f"🗣️ AI: '{no_results_response}'")
        audio_paths = generate_voice_response(no_results_response)
        if audio_paths:
            for audio_path in audio_paths:
                resp.play(url_for('main.serve_audio', filename=os.path.basename(audio_path)))
    
    # Set up gather for follow-up
    gather = Gather(
        input='speech',
        action='/voice/follow_up',
        timeout=2,
        speechTimeout='auto',
        maxTimeout=30,
        interruptible=True
    )
    resp.append(gather)
    
    logger.info("⏳ Waiting for user follow-up...")
    return str(resp)

@main.route("/voice/continue_results", methods=['POST'])
def continue_results():
    """Continue delivering remaining results if user hasn't interrupted"""
    resp = VoiceResponse()
    
    try:
        speech_result = request.values.get('SpeechResult', '')
        
        if speech_result:
            # Check if user wants to interrupt or know more about the first result
            is_interruption, interrupt_response = handle_interruption(speech_result)
            if is_interruption:
                return handle_interruption_response(resp, interrupt_response)
                
            # Check if user is asking about the first place
            place_id = conversation_context.handle_place_reference(speech_result)
            if place_id:
                details_response = format_place_details(place_id)
                audio_paths = generate_voice_response(details_response)
                
                if audio_paths:
                    for audio_path in audio_paths:
                        resp.play(url_for('main.serve_audio', filename=os.path.basename(audio_path)))
                
                # Set up gather for follow-up
                gather = Gather(
                    input='speech',
                    action='/voice/follow_up',
                    timeout=2,
                    speechTimeout='auto',
                    maxTimeout=30,
                    interruptible=True
                )
                resp.append(gather)
                
                return str(resp)
        
        # If no interruption, continue with remaining results
        if conversation_context.remaining_results:
            remaining_response = format_place_results(conversation_context.remaining_results)
            audio_chunks = generate_voice_response(remaining_response)
            
            if audio_chunks:
                for i, chunk in enumerate(audio_chunks):
                    resp.play(url_for('main.serve_audio', filename=os.path.basename(chunk)))
                    if i < len(audio_chunks) - 1:
                        gather = Gather(
                            input='speech',
                            action='/voice/follow_up',
                            timeout=2,
                            speechTimeout='auto',
                            maxTimeout=30,
                            interruptible=True
                        )
                        resp.append(gather)
        
        # Final gather for follow-up
        gather = Gather(
            input='speech',
            action='/voice/follow_up',
            timeout=5,
            speechTimeout='auto',
            maxTimeout=30,
            interruptible=True
        )
        resp.append(gather)
        
        return str(resp)
        
    except Exception as e:
        logger.error(f"Error in continue_results: {str(e)}")
        logger.exception("Full error traceback:")
        resp.say("I apologize, but I'm having trouble continuing. Would you like me to start over?")
        return str(resp)

def format_quick_results(results):
    """Format just the first result for quick response"""
    if not results:
        return "I'm searching for places that match your request..."
        
    result = results[0]
    place = result.metadata
    conversation_context.set_current_place(result.id, place)
    
    quick_response = f"I found {place.get('title', 'a place')} that might be perfect!"
    
    # Add key highlights based on place type
    if place.get('category') == 'activity':
        if place.get('features'):
            quick_response += f" They offer {place.get('features')}"
    
    if place.get('rating'):
        quick_response += f" It has {place.get('rating')} stars"
        
    if place.get('price_level'):
        price_desc = {
            '$': 'and is budget-friendly',
            '$$': 'with moderate prices',
            '$$$': 'for a nice experience',
            '$$$$': 'for something special'
        }
        quick_response += f" {price_desc.get(place.get('price_level'), '')}"
        
    quick_response += ". Would you like to hear more about this place, or shall I continue with other great options I found?"
    
    return quick_response

@main.route("/voice/follow_up", methods=['POST'])
def handle_follow_up():
    """Handle follow-up questions with enhanced intelligence"""
    resp = VoiceResponse()
    
    logger.info("\n=== Processing Follow-up Request ===")
    speech_result = request.values.get('SpeechResult', '')
    logger.info(f"👤 User Query: '{speech_result}'")
    
    if not speech_result:
        logger.warning("⚠️ No speech detected in request")
        return handle_no_speech(resp)
    
    # Add user query to history
    logger.info("📝 Adding query to conversation history")
    add_to_history(speech_result, None, 'user_query')
    
    # First check for place references
    logger.info("🔍 Checking for place references...")
    place_id = conversation_context.handle_place_reference(speech_result)
    
    if place_id:
        logger.info(f"✅ Found reference to place ID: {place_id}")
        logger.info("📊 Fetching place details from Pinecone...")
        place_details = get_place_details(place_id)
        
        if place_details:
            logger.info(f"📍 Retrieved place: {place_details.get('title', 'Unknown')}")
            logger.info("🗣️ Formatting place details for natural conversation...")
            response_text = format_place_details(place_details)
            logger.info(f"💬 Generated response: '{response_text}'")
            
            logger.info("🎵 Generating voice response...")
            audio_paths = generate_voice_response(response_text)
            if audio_paths:
                logger.info(f"✅ Generated {len(audio_paths)} audio segments")
                for audio_path in audio_paths:
                    resp.play(url_for('main.serve_audio', filename=os.path.basename(audio_path)))
            
            gather = Gather(
                input='speech',
                action='/voice/follow_up',
                timeout=2,
                speechTimeout='auto',
                maxTimeout=30,
                interruptible=True
            )
            resp.append(gather)
            logger.info("⏳ Waiting for next user input...")
            return str(resp)
        else:
            logger.error("❌ Failed to retrieve place details from Pinecone")
    
    # If no place reference found, process as a new query
    logger.info("📝 Processing as new search query...")
    query_info = process_user_query(speech_result, conversation_context)
    logger.info(f"📊 Processed query info: {json.dumps(query_info, indent=2)}")
    
    # Handle different action types
    if query_info['query_type'] == 'REFERENCE':
        logger.info("🔄 Handling as reference query")
        if conversation_context.current_results:
            logger.info(f"📍 Using {len(conversation_context.current_results)} current results")
            results = conversation_context.current_results
            response_text = generate_response(speech_result, results, conversation_context)
        else:
            logger.warning("⚠️ No current results found for reference")
            response_text = "I'm not sure which place you're referring to. Could you please be more specific?"
    else:
        # Handle as new search
        logger.info("🔎 Performing new search in Pinecone...")
        results = search_places(
            query_info,
            excluded_ids=conversation_context.rejected_places,
            top_k=5,
            sort_by='best_match'
        )
        
        if results:
            logger.info(f"✅ Found {len(results)} matching places")
            logger.info("📝 Adding results to conversation context...")
            results = conversation_context.add_search_results(results, query_info)
            response_text = generate_response(speech_result, results, conversation_context)
        else:
            logger.warning("⚠️ No results found for search criteria")
            response_text = "I couldn't find any places matching those criteria. Would you like me to try a different search?"
    
    logger.info(f"🗣️ Generated response: '{response_text}'")
    logger.info("🎵 Converting response to speech...")
    audio_paths = generate_voice_response(response_text)
    
    if audio_paths:
        logger.info(f"✅ Generated {len(audio_paths)} audio segments")
        for audio_path in audio_paths:
            resp.play(url_for('main.serve_audio', filename=os.path.basename(audio_path)))
    
    gather = Gather(
        input='speech',
        action='/voice/follow_up',
        timeout=2,
        speechTimeout='auto',
        maxTimeout=30,
        interruptible=True
    )
    resp.append(gather)
    
    logger.info("⏳ Waiting for next user input...")
    return str(resp)

@main.route('/audio/<filename>')
def serve_audio(filename):
    """Serve generated audio files"""
    try:
        if not os.path.exists(os.path.join(TEMP_AUDIO_DIR, filename)):
            logger.error(f"Audio file not found: {filename}")
            return "Audio file not found", 404
            
        return send_from_directory(
            TEMP_AUDIO_DIR,
            filename,
            as_attachment=True
        )
    except Exception as e:
        logger.error(f"Error serving audio file: {str(e)}")
        return "Error serving audio file", 500
    finally:
        try:
            # Clean up the audio file after serving
            cleanup_audio_file(os.path.join(TEMP_AUDIO_DIR, filename))
        except Exception as cleanup_error:
            logger.error(f"Error cleaning up audio file: {str(cleanup_error)}")

def handle_interruption_response(resp, interrupt_response):
    """Handle user interruption with appropriate response"""
    try:
        # Generate audio for interruption response
        audio_paths = generate_voice_response(interrupt_response)
        
        if audio_paths:
            # Play the interruption response
            for audio_path in audio_paths:
                resp.play(url_for('main.serve_audio', filename=os.path.basename(audio_path)))
        
        # Set up gather for follow-up
        gather = Gather(
            input='speech',
            action='/voice/follow_up',
            timeout=2,
            speechTimeout='auto',
            maxTimeout=30,
            interruptible=True
        )
        resp.append(gather)
        
        return str(resp)
        
    except Exception as e:
        logger.error(f"Error handling interruption: {str(e)}")
        logger.exception("Full error traceback:")
        resp.say("I apologize, but I'm having trouble understanding. Could you please repeat that?")
        return str(resp)

def handle_no_results(resp):
    """Handle case when no results are found"""
    try:
        error_message = "I couldn't find any places matching those criteria. Could you tell me more about what you're looking for?"
        audio_paths = generate_voice_response(error_message)
        
        if audio_paths:
            resp.play(url_for('main.serve_audio', filename=os.path.basename(audio_paths[0])))
            
        # Add gather for retry
        gather = Gather(
            input='speech',
            action='/voice/process',
            timeout=2,
            speechTimeout='auto',
            interruptible=True
        )
        resp.append(gather)
        
        return str(resp)
        
    except Exception as e:
        logger.error(f"Error in handle_no_results: {str(e)}")
        resp.say("I'm having trouble finding places right now. Could you try again?")
        return str(resp)

def handle_no_speech(resp):
    """Handle case when no speech is detected"""
    try:
        prompt = "I didn't catch that. Could you please repeat what you're looking for?"
        audio_paths = generate_voice_response(prompt)
        
        if audio_paths:
            resp.play(url_for('main.serve_audio', filename=os.path.basename(audio_paths[0])))
            
        gather = Gather(
            input='speech',
            action='/voice/process',
            timeout=2,
            speechTimeout='auto',
            interruptible=True
        )
        resp.append(gather)
        
        return str(resp)
        
    except Exception as e:
        logger.error(f"Error in handle_no_speech: {str(e)}")
        resp.say("I'm having trouble understanding. Please try again.")
        return str(resp)

def handle_error(resp):
    """Handle general processing errors"""
    try:
        error_message = "I apologize, but I'm having trouble processing your request. Could you try asking in a different way?"
        audio_paths = generate_voice_response(error_message)
        
        if audio_paths:
            resp.play(url_for('main.serve_audio', filename=os.path.basename(audio_paths[0])))
            
        gather = Gather(
            input='speech',
            action='/voice/process',
            timeout=2,
            speechTimeout='auto',
            interruptible=True
        )
        resp.append(gather)
        
        return str(resp)
        
    except Exception as e:
        logger.error(f"Error in handle_error: {str(e)}")
        resp.say("I'm having technical difficulties. Please try again later.")
        return str(resp) 