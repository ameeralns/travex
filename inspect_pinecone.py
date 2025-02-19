from pinecone import Pinecone
import os
from dotenv import load_dotenv
import json
from openai import OpenAI
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

def create_embedding(text):
    """Create an embedding using OpenAI's API"""
    try:
        client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        response = client.embeddings.create(
            input=text,
            model="text-embedding-ada-002",
            encoding_format="float"
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"Error creating embedding: {e}")
        return None

def inspect_pinecone_index():
    try:
        # Initialize Pinecone client
        pc = Pinecone(api_key=os.getenv('PINECONE_API_KEY'))
        index = pc.Index(os.getenv('PINECONE_INDEX_NAME'))
        
        # 1. Basic Index Statistics
        print("\n=== 1. Index Statistics ===")
        stats = index.describe_index_stats()
        print(f"Total vector count: {stats.total_vector_count}")
        print(f"Dimension: {stats.dimension}")
        
        if hasattr(stats, 'namespaces'):
            print("\nNamespaces:")
            for ns, count in stats.namespaces.items():
                print(f"- {ns}: {count} vectors")
        
        # 2. Category Distribution
        print("\n=== 2. Category Analysis ===")
        categories = {}
        cities = set()
        
        # Sample 100 records to get distribution
        query_response = index.query(
            vector=[0] * stats.dimension,
            top_k=100,
            include_metadata=True
        )
        
        for match in query_response.matches:
            if 'category' in match.metadata:
                cat = match.metadata['category']
                categories[cat] = categories.get(cat, 0) + 1
            if 'city' in match.metadata:
                cities.add(match.metadata['city'])
        
        print("\nCategory Distribution:")
        for cat, count in sorted(categories.items(), key=lambda x: x[1], reverse=True):
            print(f"{cat}: {count}")
        
        # 3. Restaurant-Specific Search
        print("\n=== 3. Restaurant Search Test ===")
        restaurant_embedding = create_embedding("mexican restaurant in austin")
        
        if restaurant_embedding:
            restaurant_results = index.query(
                vector=restaurant_embedding,
                top_k=5,
                include_metadata=True,
                filter={"city": "Austin"}  # Test exact case match
            )
            
            print("\nRestaurant Search Results (with filter):")
            for i, match in enumerate(restaurant_results.matches, 1):
                print(f"\nResult {i}:")
                print(f"Title: {match.metadata.get('title', 'N/A')}")
                print(f"Category: {match.metadata.get('category', 'N/A')}")
                print(f"Score: {match.score}")
        
        # 4. Metadata Field Analysis
        print("\n=== 4. Metadata Field Analysis ===")
        field_stats = {}
        
        for match in query_response.matches:
            for field, value in match.metadata.items():
                if field not in field_stats:
                    field_stats[field] = {
                        'count': 0,
                        'empty': 0,
                        'sample_values': set()
                    }
                field_stats[field]['count'] += 1
                if not value:
                    field_stats[field]['empty'] += 1
                if len(field_stats[field]['sample_values']) < 3:
                    field_stats[field]['sample_values'].add(str(value))
        
        print("\nField Statistics:")
        for field, stats in field_stats.items():
            print(f"\n{field}:")
            print(f"Present in {stats['count']}/100 records")
            print(f"Empty in {stats['empty']} records")
            print(f"Sample values: {', '.join(list(stats['sample_values'])[:3])}")
        
        # 5. City Case Sensitivity Test
        print("\n=== 5. City Case Sensitivity Test ===")
        print("\nCities found:", sorted(list(cities)))
        
        # Test search with different case variations
        test_cases = ["Austin", "austin", "AUSTIN"]
        for city in test_cases:
            results = index.query(
                vector=[0] * stats.dimension,
                top_k=1,
                include_metadata=True,
                filter={"city": city}
            )
            print(f"\nSearch with city='{city}': {len(results.matches)} results")
        
        # 6. Review Field Consistency
        print("\n=== 6. Review Field Analysis ===")
        review_fields = {
            'review_count': 0,
            'reviews': 0,
            'review_rating': 0,
            'rating': 0
        }
        
        for match in query_response.matches:
            for field in review_fields:
                if field in match.metadata:
                    review_fields[field] += 1
        
        print("\nReview field usage:")
        for field, count in review_fields.items():
            print(f"{field}: present in {count}/100 records")
        
    except Exception as e:
        logger.error(f"Error inspecting index: {str(e)}")
        raise

if __name__ == "__main__":
    inspect_pinecone_index() 