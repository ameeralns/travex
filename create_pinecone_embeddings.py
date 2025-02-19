import pandas as pd
from pinecone import Pinecone, ServerlessSpec
from openai import OpenAI
import os
import json
from tqdm import tqdm
import time
from dotenv import load_dotenv
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# Initialize Pinecone
PINECONE_API_KEY = os.getenv('PINECONE_API_KEY')
PINECONE_ENVIRONMENT = os.getenv('PINECONE_ENVIRONMENT')
INDEX_NAME = os.getenv('PINECONE_INDEX_NAME')

if not all([PINECONE_API_KEY, PINECONE_ENVIRONMENT, INDEX_NAME]):
    raise ValueError("Missing required environment variables. Please check your .env file.")

def create_index_if_not_exists():
    """Create Pinecone index if it doesn't exist"""
    try:
        pc = Pinecone(api_key=PINECONE_API_KEY)
        
        # Check if index already exists
        existing_indexes = [index.name for index in pc.list_indexes()]
        
        if INDEX_NAME not in existing_indexes:
            logger.info(f"Creating new index: {INDEX_NAME}")
            pc.create_index(
                name=INDEX_NAME,
                dimension=1536,  # dimensionality of text-embedding-ada-002
                metric='cosine',
                spec=ServerlessSpec(
                    cloud='aws',
                    region='us-west-2'
                )
            )
            time.sleep(10)  # Wait for index to be ready
        
        return pc.Index(INDEX_NAME)
    except Exception as e:
        logger.error(f"Error creating index: {e}")
        raise

def parse_json_field(field, default=None):
    """Safely parse JSON field"""
    if pd.isna(field):
        return default
    try:
        return json.loads(field)
    except:
        return default

def extract_features_from_about(about_json):
    """Extract relevant features from the about field"""
    features = []
    try:
        about_data = parse_json_field(about_json, [])
        for section in about_data:
            section_name = section.get('name', '')
            options = [opt['name'] for opt in section.get('options', []) 
                      if opt.get('enabled', False)]
            if options:
                features.append(f"{section_name}: {', '.join(options)}")
    except Exception as e:
        logger.warning(f"Error parsing about data: {e}")
    return features

def create_rich_text_for_embedding(row):
    """Create rich text description for embedding"""
    components = []
    
    # Basic information
    components.append(f"{row['title']} is a {row['category']}")
    
    # Location information
    address_data = parse_json_field(row['complete_address'], {})
    location_parts = []
    if address_data.get('street'):
        location_parts.append(address_data['street'])
    if address_data.get('borough'):
        location_parts.append(f"in the {address_data['borough']} area")
    if address_data.get('city'):
        location_parts.append(f"in {address_data['city']}, {address_data.get('state', 'Texas')}")
    if location_parts:
        components.append(f"Located at {', '.join(location_parts)}")
    
    # Description
    if pd.notna(row['descriptions']):
        components.append(str(row['descriptions']))
    
    # Features and amenities from about field
    features = extract_features_from_about(row['about'])
    if features:
        components.append("Features and amenities include: " + ". ".join(features))
    
    # Hours of operation
    hours_data = parse_json_field(row['open_hours'], {})
    if hours_data:
        components.append("Operating hours: " + str(hours_data))
    
    # Ratings and reviews
    if pd.notna(row['review_rating']):
        components.append(f"Rated {row['review_rating']} stars based on {row['review_count']} reviews")
    
    # Price information
    if pd.notna(row['price_range']):
        components.append(f"Price level: {row['price_range']}")
    
    # Additional context from user reviews
    if pd.notna(row.get('user_reviews')):
        reviews_data = parse_json_field(row['user_reviews'], [])
        review_texts = []
        for review in reviews_data[:3]:  # Include top 3 reviews
            if review.get('Text'):
                review_texts.append(review['Text'])
        if review_texts:
            components.append("Customer reviews mention: " + " ".join(review_texts))
    
    return " ".join(components)

def create_enhanced_metadata(row):
    """Create enhanced metadata for better filtering and retrieval"""
    address_data = parse_json_field(row['complete_address'], {})
    about_data = extract_features_from_about(row['about'])
    
    metadata = {
        'title': str(row['title']),
        'category': str(row['category']),
        'address': str(row['address']) if pd.notna(row['address']) else '',
        'city': address_data.get('city', '').strip(),
        'state': address_data.get('state', 'Texas'),
        'borough': address_data.get('borough', ''),
        'postal_code': address_data.get('postal_code', ''),
        'rating': float(row['review_rating']) if pd.notna(row['review_rating']) else 0.0,
        'reviews': int(row['review_count']) if pd.notna(row['review_count']) else 0,
        'price_level': str(row['price_range']) if pd.notna(row['price_range']) else '',
        'description': str(row['descriptions']) if pd.notna(row['descriptions']) else '',
        'latitude': float(row['latitude']) if pd.notna(row['latitude']) else 0.0,
        'longitude': float(row['longitude']) if pd.notna(row['longitude']) else 0.0,
        'phone': str(row['phone']) if pd.notna(row['phone']) else '',
        'website': str(row['website']) if pd.notna(row['website']) else '',
        'hours': str(row['open_hours']) if pd.notna(row['open_hours']) else '',
        'about': json.dumps(about_data) if about_data else '',
        'google_maps_link': str(row['link']) if pd.notna(row['link']) else '',
        'reviews_link': str(row['reviews_link']) if pd.notna(row['reviews_link']) else '',
        'thumbnail': str(row['thumbnail']) if pd.notna(row['thumbnail']) else ''
    }
    
    # Add price numeric value for better filtering
    if pd.notna(row['price_range']):
        price_str = str(row['price_range'])
        if price_str.startswith('$'):
            metadata['price_numeric'] = len(price_str.split('$')[0]) + 1
    
    return metadata

def create_embedding(text):
    """Create embedding using OpenAI's API"""
    if not text or pd.isna(text):
        return None
        
    try:
        response = client.embeddings.create(
            input=text,
            model="text-embedding-ada-002"
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"Error creating embedding: {e}")
        return None

def process_batch(index, batch_df, batch_size=100):
    """Process a batch of records with enhanced text and metadata"""
    vectors = []
    
    for idx, row in batch_df.iterrows():
        try:
            # Create rich text for embedding
            text_for_embedding = create_rich_text_for_embedding(row)
            
            # Create embedding
            embedding = create_embedding(text_for_embedding)
            if embedding is None:
                logger.warning(f"Skipping row {idx} due to embedding creation failure")
                continue
            
            # Create enhanced metadata
            metadata = create_enhanced_metadata(row)
            
            # Create vector object
            vector = {
                'id': f"place_{idx}",
                'values': embedding,
                'metadata': metadata
            }
            
            vectors.append(vector)
            
        except Exception as e:
            logger.error(f"Error processing row {idx}: {e}")
            continue
    
    if vectors:
        try:
            index.upsert(vectors=vectors)
            logger.info(f"Successfully upserted {len(vectors)} vectors")
        except Exception as e:
            logger.error(f"Error upserting vectors: {e}")
            raise

def main():
    """Main function to process the CSV and create embeddings"""
    try:
        # Create or get index
        index = create_index_if_not_exists()
        
        # Read CSV file
        logger.info("Reading CSV file...")
        df = pd.read_csv('ScrappedCitycopy.csv')
        logger.info(f"Loaded {len(df)} records from CSV")
        
        # Process in batches
        batch_size = 100
        for i in tqdm(range(0, len(df), batch_size)):
            batch_df = df.iloc[i:i + batch_size]
            process_batch(index, batch_df, batch_size)
            time.sleep(1)  # Rate limiting
        
        logger.info("Embedding creation completed successfully")
        
    except Exception as e:
        logger.error(f"Error in main process: {e}")
        raise

if __name__ == "__main__":
    main()