from flask import Flask
from dotenv import load_dotenv
import os
import logging
from openai import OpenAI
from elevenlabs import set_api_key, voices
from pinecone import Pinecone

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

load_dotenv()

# Global service clients
_openai_client = None
_pinecone_client = None
_pinecone_index = None

def init_openai():
    """Initialize OpenAI client"""
    global _openai_client
    logger.info("🔄 Initializing OpenAI client...")
    try:
        # First, ensure we have the API key
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set")
        
        # Initialize with just the API key
        _openai_client = OpenAI(api_key=api_key)
        
        # Test the client with a simple completion
        logger.debug("Testing OpenAI connection...")
        try:
            response = _openai_client.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=[{"role": "user", "content": "test"}],
                max_tokens=5
            )
            
            if not response or not response.choices:
                raise ValueError("OpenAI test request failed to return expected response")
                
            logger.info("✅ OpenAI client initialized and tested successfully")
            return True
            
        except Exception as api_error:
            logger.error(f"❌ OpenAI API test failed: {str(api_error)}")
            raise
            
    except Exception as e:
        logger.error(f"❌ Failed to initialize OpenAI client: {str(e)}")
        logger.exception("Full error traceback:")
        return False

def init_pinecone():
    """Initialize Pinecone client and index"""
    global _pinecone_client, _pinecone_index
    logger.info("🔄 Initializing Pinecone client...")
    try:
        _pinecone_client = Pinecone(api_key=os.getenv('PINECONE_API_KEY'))
        _pinecone_index = _pinecone_client.Index(os.getenv('PINECONE_INDEX_NAME'))
        # Test the connection
        _pinecone_index.describe_index_stats()
        logger.info("✅ Pinecone client initialized successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to initialize Pinecone client: {str(e)}")
        logger.exception("Full error traceback:")
        return False

def init_elevenlabs():
    """Initialize ElevenLabs configuration"""
    logger.info("🔄 Initializing ElevenLabs configuration...")
    try:
        set_api_key(os.getenv('ELEVENLABS_API_KEY'))
        from app.services.voice_service import initialize_voices
        
        if initialize_voices():
            logger.info("✅ ElevenLabs initialized successfully with voice list")
            return True
        else:
            logger.error("❌ Failed to initialize ElevenLabs voices")
            return False
            
    except Exception as e:
        logger.error(f"❌ Failed to initialize ElevenLabs: {str(e)}")
        logger.exception("Full error traceback:")
        return False

def get_openai_client():
    """Get the global OpenAI client"""
    global _openai_client
    if _openai_client is None:
        if not init_openai():
            raise RuntimeError("OpenAI client not initialized")
    return _openai_client

def get_pinecone_client():
    """Get the global Pinecone client"""
    global _pinecone_client
    if _pinecone_client is None:
        if not init_pinecone():
            raise RuntimeError("Pinecone client not initialized")
    return _pinecone_client

def get_pinecone_index():
    """Get the global Pinecone index"""
    global _pinecone_index
    if _pinecone_index is None:
        if not init_pinecone():
            raise RuntimeError("Pinecone index not initialized")
    return _pinecone_index

def create_app():
    """Create and configure the Flask application"""
    logger.info("🚀 Starting app creation...")
    app = Flask(__name__)
    
    # Ensure all required environment variables are set
    required_env_vars = [
        'OPENAI_API_KEY',
        'PINECONE_API_KEY',
        'PINECONE_ENVIRONMENT',
        'PINECONE_INDEX_NAME',
        'TWILIO_ACCOUNT_SID',
        'TWILIO_AUTH_TOKEN',
        'TWILIO_PHONE_NUMBER',
        'ELEVENLABS_API_KEY'
    ]
    
    logger.info("🔍 Checking environment variables...")
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        error_msg = f"Missing required environment variables: {', '.join(missing_vars)}"
        logger.error(f"❌ {error_msg}")
        raise RuntimeError(error_msg)
    logger.info("✅ All environment variables present")
    
    # Initialize all services
    services_status = {
        "OpenAI": init_openai(),
        "Pinecone": init_pinecone(),
        "ElevenLabs": init_elevenlabs()
    }
    
    # Check if all services initialized successfully
    failed_services = [name for name, status in services_status.items() if not status]
    if failed_services:
        error_msg = f"Failed to initialize services: {', '.join(failed_services)}"
        logger.error(f"❌ {error_msg}")
        raise RuntimeError(error_msg)
    
    logger.info("✅ All services initialized successfully")
    
    # Import and register blueprints
    logger.info("📝 Registering routes...")
    from app.routes import main
    app.register_blueprint(main)
    
    logger.info("✨ App creation completed successfully!")
    return app 