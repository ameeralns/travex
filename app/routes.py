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
        # Initialize conversation context for new call
        conversation_context.conversation_history = []
        conversation_context.call_start_time = datetime.now()
        conversation_context.previous_queries = []
        conversation_context.previous_responses = []
        conversation_context.mentioned_places = set()
        conversation_context.user_preferences = {}
        conversation_context.current_voice = None
        
        # Initial greeting with new random voice
        greeting = get_initial_greeting()
        greeting_audio_paths = generate_voice_response(greeting)
        
        if not greeting_audio_paths:
            # Handle complete failure case
            resp.say("I apologize, but I'm having trouble connecting. Please try again later.")
            return str(resp)
            
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
        
        return str(resp)
        
    except Exception as e:
        logger.error(f"Error in voice route: {str(e)}")
        logger.exception("Full error traceback:")
        resp.say("I apologize, but I'm having trouble connecting. Please try again later.")
        return str(resp)

@main.route("/voice/process", methods=['POST'])
def process_voice():
    """Process voice input with progressive responses"""
    resp = VoiceResponse()
    
    try:
        speech_result = request.values.get('SpeechResult', '')
        
        if not speech_result:
            return handle_no_speech(resp)
            
        # Add quick acknowledgment
        quick_ack = "Let me find that for you..."
        ack_audio = generate_voice_response(quick_ack)[0]
        resp.play(url_for('main.serve_audio', filename=os.path.basename(ack_audio)))
        
        # Add user query to history
        add_to_history(speech_result, None, 'user_query')
        
        # Process query with context
        query_info = process_user_query(speech_result, conversation_context)
        
        # Update context immediately
        if query_info['location'].get('city'):
            conversation_context.current_city = query_info['location']['city']
        if query_info.get('preferences'):
            update_user_preferences(query_info['preferences'])
        
        # Normal search
        results = search_places(query_info)
        results = conversation_context.add_search_results(results, query_info)
        
        if not results:
            return handle_no_results(resp)
        
        # Generate quick initial response
        quick_response = format_quick_results(results[:3])
        audio_chunks = generate_voice_response(quick_response)
        
        if audio_chunks:
            for i, chunk in enumerate(audio_chunks):
                resp.play(url_for('main.serve_audio', filename=os.path.basename(chunk)))
                # Add gather between chunks for natural interruption
                if i < len(audio_chunks) - 1:
                    gather = Gather(
                        input='speech',
                        action='/voice/follow_up',
                        timeout=1,
                        speechTimeout='auto',
                        interruptible=True
                    )
                    resp.append(gather)
        
        # Final gather with shorter timeout
        gather = Gather(
            input='speech',
            action='/voice/follow_up',
            timeout=2,
            speechTimeout=1,
            interruptible=True
        )
        resp.append(gather)
        
        return str(resp)
        
    except Exception as e:
        logger.error(f"Error in process_voice: {str(e)}")
        logger.exception("Full error traceback:")
        return handle_error(resp)

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
            place_id = handle_place_reference(speech_result)
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
    """Handle follow-up questions and continue the conversation"""
    resp = VoiceResponse()
    
    speech_result = request.values.get('SpeechResult', '')
    
    if speech_result:
        # Add user query to history
        add_to_history(speech_result, None, 'user_query')
        
        # Process query with context
        query_info = process_user_query(speech_result, conversation_context)
        
        # Get the action type from context
        action_type = query_info['context'].get('action_type', 'new_search')
        
        # Handle different action types
        if action_type == 'get_place_details':
            # User wants more details about current place
            response_text = handle_aspect_query('overview', 
                conversation_context.current_place['metadata'],
                conversation_context
            )
        elif action_type == 'get_more_results':
            # User wants to hear more results from current search
            results = conversation_context.get_next_results(3)
            if results:
                response_text = generate_response(speech_result, results, conversation_context)
            else:
                response_text = "I've shown you all the places I know that match your preferences. Would you like me to look for something different?"
        elif action_type == 'get_alternatives':
            # User wants different options
            if conversation_context.current_place:
                conversation_context.mark_place_rejected(conversation_context.current_place['id'])
            results = search_places(query_info, excluded_places=conversation_context.rejected_places)
            results = conversation_context.add_search_results(results, query_info)
            if results:
                response_text = generate_response(speech_result, results, conversation_context)
            else:
                response_text = "Let me find some different options for you. What specifically are you looking for?"
        elif action_type == 'get_aspect_details':
            # User asking about specific aspect of current place
            response_text = handle_aspect_query(
                query_info['context']['specific_aspect'],
                conversation_context.current_place['metadata'],
                conversation_context
            )
        else:
            # New search
            results = search_places(query_info)
            results = conversation_context.add_search_results(results, query_info)
            if results:
                response_text = generate_response(speech_result, results, conversation_context)
            else:
                response_text = "I couldn't find any places matching those criteria. Would you like me to broaden the search?"
        
        # Generate and play audio response
        audio_chunks = generate_voice_response(response_text)
        
        if audio_chunks:
            for i, chunk in enumerate(audio_chunks):
                resp.play(url_for('main.serve_audio', filename=os.path.basename(chunk)))
                if i < len(audio_chunks) - 1:
                    gather = Gather(
                        input='speech',
                        action='/voice/follow_up',
                        timeout=1,
                        speechTimeout='auto',
                        interruptible=True
                    )
                    resp.append(gather)
        
        # Final gather
        gather = Gather(
            input='speech',
            action='/voice/follow_up',
            timeout=2,
            speechTimeout='auto',
            interruptible=True
        )
        resp.append(gather)
        
    else:
        # Generate context-aware prompt using OpenAI
        prompt_context = {
            "current_place": conversation_context.current_place['metadata'] if conversation_context.current_place else None,
            "has_more_results": bool(conversation_context.remaining_results),
            "user_preferences": conversation_context.user_preferences
        }
        response_text = generate_response("no_speech", [], conversation_context)
        
        prompt_audio = generate_voice_response(response_text)[0]
        resp.play(url_for('main.serve_audio', filename=os.path.basename(prompt_audio)))
        
        # Add prompt to history
        add_to_history('no_speech_detected', response_text, 'system_prompt')
        
        gather = Gather(
            input='speech',
            action='/voice/follow_up',
            timeout=2,
            speechTimeout='auto',
            interruptible=True
        )
        resp.append(gather)
    
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