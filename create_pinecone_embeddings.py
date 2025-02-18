import pandas as pd
from pinecone import Pinecone, ServerlessSpec
from openai import OpenAI
import os
from tqdm import tqdm
import time
from dotenv import load_dotenv

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

# Initialize Pinecone client
pc = Pinecone(api_key=PINECONE_API_KEY)

def create_index_if_not_exists():
    """Create Pinecone index with proper configuration if it doesn't exist"""
    try:
        if INDEX_NAME not in pc.list_indexes().names():
            print(f"Creating new Pinecone index: {INDEX_NAME}")
            pc.create_index(
                name=INDEX_NAME,
                dimension=1536,  # dimensionality of text-embedding-ada-002
                metric='cosine',
                spec=ServerlessSpec(
                    cloud='aws',
                    region='us-east-1'
                )
            )
            print("Waiting for index to be ready...")
            time.sleep(10)  # Give time for the index to initialize
        return pc.Index(INDEX_NAME)
    except Exception as e:
        print(f"Error creating index: {e}")
        raise

def create_embedding(text):
    """Create embedding using OpenAI's API"""
    if not text or pd.isna(text):
        return None
        
    try:
        response = client.embeddings.create(
            input=text,
            model="text-embedding-ada-002"  # This model creates 1536-dimensional embeddings
        )
        return response.data[0].embedding
    except Exception as e:
        print(f"Error creating embedding: {e}")
        return None

def process_batch(index, batch_df, batch_size=100):
    """Process a batch of records"""
    vectors = []
    
    for idx, row in batch_df.iterrows():
        try:
            # Create a rich text description for embedding
            text_for_embedding = f"{row['title']} is a {row['category']} located at {row['address']}. "
            
            # Add additional details if available
            if pd.notna(row.get('descriptions', '')):
                text_for_embedding += f"{row['descriptions']} "
            if pd.notna(row.get('price_range', '')):
                text_for_embedding += f"Price level: {row['price_range']}. "
            if pd.notna(row.get('review_rating', '')):
                text_for_embedding += f"Rating: {row['review_rating']} with {row['review_count']} reviews. "
            
            # Create embedding
            embedding = create_embedding(text_for_embedding)
            if embedding is None:
                print(f"Skipping row {idx} due to embedding creation failure")
                continue
                
            # Prepare metadata
            metadata = {
                'title': str(row['title']) if pd.notna(row['title']) else '',
                'category': str(row['category']) if pd.notna(row['category']) else '',
                'address': str(row['address']) if pd.notna(row['address']) else '',
                'rating': float(row['review_rating']) if pd.notna(row['review_rating']) else 0.0,
                'reviews': int(row['review_count']) if pd.notna(row['review_count']) else 0,
                'phone': str(row['phone']) if pd.notna(row['phone']) else '',
                'website': str(row['website']) if pd.notna(row['website']) else '',
                'hours': str(row['open_hours']) if pd.notna(row['open_hours']) else '',
                'price_level': str(row['price_range']) if pd.notna(row['price_range']) else '',
                'description': str(row['descriptions']) if pd.notna(row['descriptions']) else '',
                'latitude': float(row['latitude']) if pd.notna(row['latitude']) else 0.0,
                'longitude': float(row['longitude']) if pd.notna(row['longitude']) else 0.0,
                'complete_address': str(row['complete_address']) if pd.notna(row['complete_address']) else '',
                'about': str(row['about']) if pd.notna(row['about']) else '',
                'google_maps_link': str(row['link']) if pd.notna(row['link']) else '',
                'reviews_link': str(row['reviews_link']) if pd.notna(row['reviews_link']) else '',
                'thumbnail': str(row['thumbnail']) if pd.notna(row['thumbnail']) else ''
            }
            
            # Create vector object with unique ID based on original index
            vector = {
                'id': f"place_{idx}",
                'values': embedding,
                'metadata': metadata
            }
            
            vectors.append(vector)
            
        except Exception as e:
            print(f"Error processing row {idx}: {e}")
            continue
    
    if vectors:
        try:
            # Upsert to Pinecone
            index.upsert(vectors=vectors)
            print(f"Successfully uploaded batch of {len(vectors)} vectors")
        except Exception as e:
            print(f"Error upserting vectors to Pinecone: {e}")

def main():
    try:
        # Read the CSV file
        print("Reading CSV file...")
        df = pd.read_csv('ScrappedCitycopy.csv')
        
        # Initialize Pinecone index
        index = create_index_if_not_exists()
        
        # Process in batches
        batch_size = 100
        total_batches = len(df) // batch_size + (1 if len(df) % batch_size != 0 else 0)
        
        print(f"\nProcessing {len(df)} records in {total_batches} batches...")
        
        for i in tqdm(range(0, len(df), batch_size)):
            batch_df = df.iloc[i:i+batch_size]
            process_batch(index, batch_df, batch_size)
            time.sleep(1)  # Rate limiting
        
        # Print final statistics
        stats = index.describe_index_stats()
        print("\nEmbedding creation completed!")
        print(f"Total vectors in index: {stats.total_vector_count}")
        
    except Exception as e:
        print(f"An error occurred: {e}")
        raise

if __name__ == "__main__":
    main()